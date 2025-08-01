from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from yt_dlp import YoutubeDL
from pathlib import Path
from zipfile import ZipFile
import os
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
import asyncio
from fastapi import BackgroundTasks


def clear_downloads_folder():
    folder = "downloads"
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}: {e}")

app = FastAPI()
# progress_queue = asyncio.Queue()

# Allow frontend requests from React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_methods=["*"],
    allow_headers=["*"],
)
# Make sure 'downloads' folder exists
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR = str(DOWNLOAD_DIR)

# Mount a /downloads route to serve files from the folder
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

class DownloadRequest(BaseModel):
    url: str
    start: int
    end: int

progress_messages = []

@app.post("/download")
async def process_download(request: DownloadRequest):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': DOWNLOAD_DIR + '/%(title)s.%(ext)s',
        'overwrites': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    # Clean up old ZIPs before download
    clear_downloads_folder()

    with YoutubeDL({'extract_flat': True, 'quiet': True}) as ydl:
        playlist = ydl.extract_info(request.url, download=False)
        try:
            entries = playlist['entries'][request.start:request.end]
        except Exception as e:
            print(f"Error occurred while extracting info: {e}")
            raise HTTPException(status_code=500, detail="Failed to extract YouTube info, check if the playlist URL is correct")
        filenames = []
        total = len(entries)
        for i,entry in enumerate(entries):
            video_id = entry.get('id')
            print("\n entry check" + str(i))
            if video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                try:                    
                    video_title = entry.get('title', None)
                    filenames.append(video_title + ".mp3")
                    print(f"🔁 Putting into queue: Downloading {video_title} ({i+1}/{total})")
                    progress_messages.append(f"Downloading {video_title} ({i+1}/{total})")
                    with YoutubeDL(ydl_opts) as mp3_ydl:
                        mp3_ydl.download([video_url])
                except Exception as e:
                    print(f"❌ Failed to download {video_url}: {e}")
                    progress_messages.append(f"Failed to download {video_title}")
        
            print("\n entry check end")
        progress_messages.append(f"Downloading complete")

    
    print("trying to zip files")
    # Zip the files
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    zip_filename = f"{DOWNLOAD_DIR}/playlist_{timestamp}.zip"

    # Only include .mp3 files, skip existing zip files
    with ZipFile(zip_filename, 'w') as zipf:
        for file in filenames:
            if file.endswith(".mp3"):
                file_path = os.path.join("downloads", file)
                zipf.write(file_path, arcname=file)

    print("Downloads finished, returning now.")
    return {
        "status": "ok",
        "files": filenames,
        "zip": zip_filename.replace(DOWNLOAD_DIR+"/", "")
    }

@app.get("/progress")
async def progress():
    async def event_generator():
        previous = 0
        while True:
            if len(progress_messages) > previous:
                # Send only new messages
                for msg in progress_messages[previous:]:
                    yield f"data: {msg}\n\n"
                previous = len(progress_messages)
            await asyncio.sleep(1)
    return EventSourceResponse(event_generator())

@app.get("/download-file/{filename}")
def download_file(filename: str):
    file_path = os.path.join("downloads", filename)
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/octet-stream'
    )

@app.get("/send-test-message")
async def send_test_message():
    await progress_messages.append(" Test message from server.")
    return {"status": "ok"}

send_test_message()



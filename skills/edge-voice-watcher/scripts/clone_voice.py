import yt_dlp
import librosa
import soundfile as sf
import os
import numpy as np

URL = "https://www.youtube.com/watch?v=XrgImx12n6U"
START_TIME = 20 * 60 + 40  # 20:40 -> 1240s
END_TIME = 20 * 60 + 60    # 21:00 -> 1260s
OUTPUT_FILE = "kaedra_voice_new.wav"

def clone_voice():
    print(f"[*] Downloading audio from {URL}...")
    
    # Download options
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'temp_download',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([URL])
            
        print("[*] Loading audio for trimming...")
        # Find the file (yt-dlp adds .wav)
        filename = "temp_download.wav"
        
        # Load with librosa (resample to 24000 for Chatterbox or 16000? Chatterbox uses 24k/44k?)
        # Standard reference can be 22k/24k. Let's use 24000.
        y, sr = librosa.load(filename, sr=24000)
        
        # Trim
        start_sample = int(START_TIME * sr)
        end_sample = int(END_TIME * sr)
        
        print(f"[*] Trimming {START_TIME}s - {END_TIME}s ({end_sample - start_sample} samples)...")
        y_trimmed = y[start_sample:end_sample]
        
        # Save
        sf.write(OUTPUT_FILE, y_trimmed, sr)
        print(f"[+] Saved voice clone to {OUTPUT_FILE}")
        
        # Cleanup
        os.remove(filename)
        
    except Exception as e:
        print(f"[!] Error: {e}")

if __name__ == "__main__":
    clone_voice()

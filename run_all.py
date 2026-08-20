import subprocess
import sys

def main():
    print("[INFO] Starting Universal Downloader Bot...")
    p1 = subprocess.Popen([sys.executable, "bot.py"])
    
    print("[INFO] Starting Caller ID Bot...")
    p2 = subprocess.Popen([sys.executable, "caller_bot.py"])
    
    # Wait for both processes to complete
    p1.wait()
    p2.wait()

if __name__ == "__main__":
    main()

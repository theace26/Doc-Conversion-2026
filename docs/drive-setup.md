# Mounting Your Drives

MarkFlow runs inside Docker and can only access folders you explicitly share with it.

## Setup (Windows)

1. Open Docker Desktop → Settings → Resources → File Sharing
2. Add each drive you want MarkFlow to read from (C:\, D:\, etc.)
3. Click Apply & Restart

4. In docker-compose.yml, add a volume line for each drive:
       - C:/:/host/c:ro
       - D:/:/host/d:ro

5. Add the same letters to `MOUNTED_DRIVES` in your `.env` file:
       MOUNTED_DRIVES=c,d

6. Restart MarkFlow:
       docker-compose down && docker-compose up -d

## In MarkFlow

Once drives are mounted, go to Locations and click "Browse" to
pick a folder visually — no need to type container paths manually.

Your drives appear as:
  C:\ → /host/c
  D:\ → /host/d

## Output Folder

Your output folder needs to be writable. The default is:
  C:\Users\{YourName}\markflow-output → /mnt/output-repo

Change this in docker-compose.yml if you want output elsewhere.

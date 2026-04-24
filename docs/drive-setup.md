# Mounting Your Drives

MarkFlow runs inside Docker and can only access folders you explicitly share with it.

## Setup (Windows)

1. Open Docker Desktop → Settings → Resources → File Sharing
2. Add each drive you want MarkFlow to read from (C:\, D:\, etc.)
3. Click Apply & Restart

4. In docker-compose.yml, add a volume line for each drive:
       - C:/:/host/c
       - D:/:/host/d

   (Before v0.29.2 these were `:ro`. They are now writable so you can
   choose a drive path as the output folder; the app-level write guard
   still blocks writes outside the configured output directory.)

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

As of v0.29.2 you can also pick an output folder directly on a mounted
drive via the Storage page (for example `/host/d/markflow-output`). The
app-level write guard restricts writes to the configured output
directory only — picking `/host/d/foo` as output does not grant write
access to the rest of `/host/d`.

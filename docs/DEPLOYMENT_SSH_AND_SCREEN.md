# Server access: SSH key (PEM) and Screen sessions

This guide assumes you deploy DocuStay on a Linux server (for example AWS EC2) and run the backend and frontend in **GNU Screen** sessions.

## 1. PEM key URL and local file

- **Download URL for your `.pem` key** (set this to your real link—for example the object URL in S3, or the path shown in your cloud provider’s console after you create or download the key pair):  
  **`https://YOUR-STORAGE-OR-CONSOLE-URL/YOUR-KEY.pem`**

- Save the file on your machine (e.g. `DocuStay.pem`). On **Windows**, put it in a folder you remember (for example `C:\Users\YourName\.ssh\` or your project folder).

- **Permissions (Linux/macOS):** so SSH will accept the key:

  ```bash
  chmod 400 /path/to/YOUR-KEY.pem
  ```

## 2. Open a terminal in the folder where the PEM file lives

- **Windows (PowerShell):**  
  `cd` to the directory that contains `YOUR-KEY.pem`, for example:

  ```powershell
  cd C:\Users\YourName\.ssh
  ```

- **macOS / Linux:** same idea—`cd` to the directory that contains the key.

## 3. SSH into the server

Replace the user, host, and key name with your values (EC2 often uses `ec2-user` or `ubuntu`):

```bash
ssh -i YOUR-KEY.pem ec2-user@YOUR_SERVER_IP_OR_HOSTNAME
```

If your provider documents a different username or port, use that (example with port 22 implied).

## 4. Go to the project directory on the server

On the server, change to your app root (use **your** path; common layouts are under `/var/www`):

```bash
cd /var/www/myproject
```

If your server uses a different path (for example `/www/var/myproject`), use that path instead.

## 5. Backend: attach to Screen, start or stop the server

List or attach to the backend session:

```bash
screen -r backend
```

- Start or stop the backend process as you normally do on that host (for example `uvicorn` with a process manager, or the commands your deployment uses).
- **Detach** from Screen without closing the server: press **`Ctrl+A`**, then **`D`** (release both keys, then type `d`). You return to a normal shell while the session keeps running.

If `screen -r backend` says there is no such session, create one first:

```bash
screen -S backend
```

Then start the backend inside that session, and detach with **`Ctrl+A`** then **`D`**.

## 6. Frontend: same pattern

```bash
screen -r frontend
```

Manage the frontend (e.g. `npm run` / Node / static server—whatever your deployment uses), then detach with **`Ctrl+A`** then **`D`**.

If the session does not exist yet:

```bash
screen -S frontend
```

## 7. Quick reference

| Step | Action |
|------|--------|
| Key file | Download from your PEM URL; `chmod 400` on Unix-like systems |
| Terminal | Open in the folder where `YOUR-KEY.pem` is stored |
| Connect | `ssh -i YOUR-KEY.pem user@host` |
| Project | `cd /var/www/myproject` (or your actual path) |
| Backend | `screen -r backend` → work → **`Ctrl+A`** **`D`** to detach |
| Frontend | `screen -r frontend` → work → **`Ctrl+A`** **`D`** to detach |

## 8. See all Screen sessions

```bash
screen -ls
```

---

*Repository: [DocuStay on GitHub](https://github.com/ArfaMujahid/DocuStay.git)*

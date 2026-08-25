# Hybrid Development & Cloud Deployment Rule
# Scope: Local Laptop + GitHub + Azure VM Workflow

## 1. Local Laptop (Development & Editing)
- **Editing & Testing**: Develop and test code locally inside `C:\Users\VikasKumar\Desktop\playlist`.
- **Local Server Launcher**: Run `python MCP/server.py` to test locally at `http://localhost:8000`.
- **Secret Protection**: Store sensitive API keys (`OPENAI_API_KEY`, `BC_CLIENT_SECRET`) in git-ignored `.env` files (`.env`, `MCP/.env`). Never commit raw keys to git.

## 2. GitHub (Single Source of Truth)
- **Repository**: `https://github.com/themastyogi/opsmeld-recon-engine.git`
- **Version Control**: Always verify `git status` and push changes to `main` branch before switching environments (`git push origin main`).
- **Clean Workspace**: Keep local laptop free of unused code copies; GitHub remains the master backup.

## 3. Azure VM (24/7 Production Server & Cloud Workstation)
- **Server Address**: `172.198.137.15`
- **Production URL**: `https://ar.opsmeld.com` (HTTPS SSL 🔒 active)
- **Deployment Sync**: On VM startup, sync latest changes via:
  `cd ~/projects/opsmeld-recon-engine && git pull origin main && sudo systemctl restart opsmeld`
- **Cost Optimization**: Auto-shutdown daily at 7:00 PM IST + 1-Tap Azure Mobile App (`▶️ Start` / `⏹️ Stop`) to keep costs virtually zero.

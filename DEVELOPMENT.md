# Development Guide

This document provides instructions for setting up a development environment for the Backblaze Snapshot Reporting application using Docker containers. Using Docker ensures consistent development environments across different operating systems.

## Prerequisites

### For All Platforms
- [Docker](https://docs.docker.com/get-docker/) (version 20.10 or later)
- [Docker Compose](https://docs.docker.com/compose/install/) (version 2.0 or later)
- Git
- A code editor (VS Code recommended)

### For Windows Users
- [Windows Subsystem for Linux (WSL2)](https://docs.microsoft.com/en-us/windows/wsl/install)
- [Docker Desktop for Windows](https://docs.docker.com/desktop/windows/install/) with WSL2 backend enabled
- A Linux distribution installed via WSL2 (Ubuntu 20.04 LTS recommended)

## Setup for Linux Users

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/backblaze-snapshot-reporting.git
   cd backblaze-snapshot-reporting
   ```

2. **Create a .env file**
   ```bash
   cp .env.example .env
   ```

3. **Edit the .env file with your Backblaze B2 credentials**
   ```bash
   nano .env
   ```

4. **Build and start the Docker containers using the development configuration**
   ```bash
   docker-compose -f docker-compose.dev.yml build
   docker-compose -f docker-compose.dev.yml up -d
   ```

5. **View logs**
   ```bash
   docker-compose -f docker-compose.dev.yml logs -f
   ```

6. **Access the application**
   - Open http://localhost:5000 in your web browser

## Setup for Windows Users with WSL2

1. **Install and Configure Docker Desktop for Windows**
   - Download and install [Docker Desktop for Windows](https://docs.docker.com/desktop/windows/install/)
   - Open Docker Desktop settings
   - Under "General", ensure "Use the WSL 2 based engine" is checked
   - Under "Resources" > "WSL Integration", enable integration for your WSL distribution
   - Apply and restart Docker Desktop

2. **Open WSL2 terminal**
   - Press Start, type "WSL" or "Ubuntu", and open your Linux distribution
   - Verify Docker is available in WSL2:
     ```bash
     docker --version
     docker-compose --version
     ```

3. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/backblaze-snapshot-reporting.git
   cd backblaze-snapshot-reporting
   ```

4. **Create a .env file**
   ```bash
   cp .env.example .env
   ```

5. **Edit the .env file with your Backblaze B2 credentials**
   ```bash
   nano .env
   ```

6. **Build and start the Docker containers using the development configuration**
   ```bash
   docker-compose -f docker-compose.dev.yml build
   docker-compose -f docker-compose.dev.yml up -d
   ```

7. **View the logs**
   ```bash
   docker-compose -f docker-compose.dev.yml logs -f
   ```

8. **Access the application**
   - Open http://localhost:5000 in your web browser

## Development Workflow

### Making Code Changes

1. **Start the application in development mode**
   ```bash
   # Stop any running containers first
   docker-compose -f docker-compose.dev.yml down
   
   # Start with development settings
   docker-compose -f docker-compose.dev.yml up -d
   ```

2. **Edit the code using your preferred editor**
   - The code is automatically reloaded when changes are detected thanks to the Flask debug mode
   - Changes to Python files will be applied without restarting the container
   - HTML template changes will be visible on browser refresh

3. **View real-time logs**
   ```bash
   docker-compose -f docker-compose.dev.yml logs -f
   ```

### Testing Your Changes

1. **Run tests within the container**
   ```bash
   docker-compose -f docker-compose.dev.yml exec web python -m unittest discover -s tests
   ```

2. **Manually test the application**
   - Open http://localhost:5000 in your browser
   - Test email notifications: http://localhost:5000/api/test-email
   - Check health endpoint: http://localhost:5000/api/health

## Testing Your Development Environment

We've provided scripts to help you verify that your development environment is set up correctly.

### For Linux Users:

```bash
# Make the script executable
chmod +x scripts/test_dev_environment.sh

# Run the test
./scripts/test_dev_environment.sh
```

### For Windows Users:

In WSL2:
```bash
# Make the script executable
chmod +x scripts/test_dev_environment.sh

# Run the test
./scripts/test_dev_environment.sh
```

Or in PowerShell:
```powershell
# Run the test in PowerShell
.\scripts\Test-DevEnvironment.ps1
```

These scripts will check:
- If Docker and Docker Compose are installed and available
- If WSL2 is properly configured (for Windows)
- If the necessary project files exist
- If required ports are available
- If your Docker configuration can successfully build the images

Follow any recommendations provided by the test scripts to complete your setup.

### Docker Commands Reference

```bash
# Build containers
docker-compose -f docker-compose.dev.yml build

# Start containers in the background
docker-compose -f docker-compose.dev.yml up -d

# Start containers with live output
docker-compose -f docker-compose.dev.yml up

# Stop containers
docker-compose -f docker-compose.dev.yml down

# View logs
docker-compose -f docker-compose.dev.yml logs

# Follow logs in real-time
docker-compose -f docker-compose.dev.yml logs -f

# Access a shell inside the container
docker-compose -f docker-compose.dev.yml exec web /bin/bash

# Check container status
docker-compose -f docker-compose.dev.yml ps

# Initialize the database (if needed)
docker-compose -f docker-compose.dev.yml exec web python -m scripts.init_db
```

## Configuring Visual Studio Code for Docker Development

1. **Install VS Code Extensions**
   - Docker extension
   - Remote - Containers extension
   - Remote - WSL extension (for Windows users)

2. **Attach VS Code to the Running Container**
   - Click on the Docker icon in the VS Code sidebar
   - Find the running `backblaze-snapshot-reporting_web` container
   - Right-click and select "Attach Visual Studio Code"
   - VS Code will open a new window connected to the container

3. **Configure Python Intellisense**
   - In VS Code (attached to container), open the Command Palette (Ctrl+Shift+P)
   - Type "Python: Select Interpreter" and select the Python in the container

## Debugging

### Using VS Code Debugger with Docker

Our development environment already includes a debugger port (5678) exposed in the `docker-compose.dev.yml` file. To use it:

1. **Start the application in development mode**:
   ```bash
   docker-compose -f docker-compose.dev.yml up -d
   ```

2. **Add the debugpy package to the container**:
   ```bash
   docker-compose -f docker-compose.dev.yml exec web pip install debugpy
   ```

3. **Add a debugging entrypoint in your code**:
   
   Insert this code at the beginning of `app/app.py`:

   ```python
   import debugpy
   debugpy.listen(("0.0.0.0", 5678))
   print("Waiting for debugger to attach...")
   debugpy.wait_for_client()
   ```

4. **Create a .vscode/launch.json file** (if it doesn't exist):

   ```json
   {
       "version": "0.2.0",
       "configurations": [
           {
               "name": "Python: Remote Attach",
               "type": "python",
               "request": "attach",
               "connect": {
                   "host": "localhost",
                   "port": 5678
               },
               "pathMappings": [
                   {
                       "localRoot": "${workspaceFolder}",
                       "remoteRoot": "/app"
                   }
               ]
           }
       ]
   }
   ```

5. **Attach the VS Code debugger**:
   - Switch to the "Run and Debug" view in VS Code (or press F5)
   - Select "Python: Remote Attach" from the dropdown
   - Click the play button or press F5

6. **Set breakpoints**:
   - Click in the gutter (left margin) next to the line numbers to add breakpoints
   - When execution reaches a breakpoint, VS Code will pause execution and let you inspect variables

7. **Debug tools**:
   - Step Over (F10): Execute the current line and move to the next line
   - Step Into (F11): Step into a function call
   - Step Out (Shift+F11): Run until the current function returns
   - Continue (F5): Continue execution until the next breakpoint

8. **After debugging**:
   Don't forget to remove the debugpy code before committing your changes.

## Understanding the Development Docker Compose File

The project includes a `docker-compose.dev.yml` file with development-specific settings:

```yaml
version: '3.8'

services:
  web:
    build: 
      context: .
    ports:
      - "5000:5000"
      - "5678:5678"  # Debugging port
    volumes:
      - ./app:/app/app
      - ./scripts:/app/scripts
      - backblaze_data:/data
    environment:
      - DEBUG=True
      - FLASK_ENV=development
    command: python -m flask --app app.app run --host=0.0.0.0 --port=5000 --debug
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

volumes:
  backblaze_data:
```

Key features:
- Hot reloading with Flask debug mode enabled
- Volume mounts for code changes
- Exposed debugging port (5678)
- Health checks to ensure application availability

## Common Issues and Solutions

### Permission Errors

If you encounter permission errors when mounting volumes:

```bash
# Fix permission issues with mounted volumes
sudo chown -R $(id -u):$(id -g) ./app
```

### Docker Networking Issues

If the container can't access the internet:

```bash
# Check if Docker networking is working
docker run --rm alpine ping -c 4 google.com
```

### Container Won't Start

Check for port conflicts:

```bash
# On Linux/WSL2
sudo lsof -i :5000

# On Windows (PowerShell)
netstat -ano | findstr :5000
```

### Missing Environment Variables

If the application isn't connecting to Backblaze:

```bash
# Check if .env file exists
ls -la .env

# View environment variables in the container
docker-compose -f docker-compose.dev.yml exec web env | grep B2_
```

### WSL2-Specific Issues

1. **Path mapping problems**:
   - Use Linux paths within WSL2
   - Avoid Windows paths like `C:\path\to\folder`

2. **Docker Desktop not available in WSL2**:
   - Ensure WSL integration is enabled in Docker Desktop settings

## Database Management

To access the SQLite database directly:

```bash
# Enter the container shell
docker-compose -f docker-compose.dev.yml exec web /bin/bash

# Access SQLite database
sqlite3 /data/backblaze_snapshots.db

# Run SQL commands
.tables
SELECT * FROM snapshots LIMIT 5;
SELECT * FROM notification_history LIMIT 5;
.schema
.exit
```

## Testing Email Notifications

To test the email notification system:

```bash
# Through API (Linux/WSL2)
curl http://localhost:5000/api/test-email

# Through API (Windows PowerShell)
Invoke-RestMethod http://localhost:5000/api/test-email
```

Or visit http://localhost:5000/settings and use the "Test Email Configuration" button.

## Developing Features

The application has several key features that can be customized and extended. See the following documentation for details:

- [Snapshot Scheduling](docs/SNAPSHOT_SCHEDULING.md) - Customize how and when snapshots are taken
- [Email Notifications](docs/EMAIL_NOTIFICATIONS.md) - Configure and test email alerts

## Building for Production

When you're ready to deploy to production:

```bash
# Build the production Docker image
docker-compose build

# Start the production container
docker-compose up -d
```

The primary differences in the production setup are:
- Gunicorn replaces the Flask development server
- Debug mode is disabled
- More conservative resource usage
- No hot-reloading

## Contributing Guidelines

1. Create a new branch for your feature or bug fix
2. Make your changes
3. Write or update tests as needed
4. Ensure all tests pass
5. Submit a pull request

---

For more information, refer to the [README.md](README.md) file.

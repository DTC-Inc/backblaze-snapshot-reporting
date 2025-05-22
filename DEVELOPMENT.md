# Development Guide

This document provides instructions for setting up a development environment for the Backblaze Snapshot Reporting application and outlines our standards for Docker files, environment configuration, and code development.

## Docker Stack Standards

### Docker File Structure

We maintain a consistent structure for our Docker deployment files:

- **docker-compose.yml**: The main configuration file with all services defined but minimal volume configuration
- **docker-compose.external.yml**: Override file for production with external volumes
- **docker-compose.local.yml**: Override file for development with local volumes
- **stack.env.example**: Template for environment variables, copied to stack.env for actual use

### Naming Conventions

We follow these naming conventions for Docker resources:

- **Stack Name**: All resources use the `bbssr` prefix by default (configurable via STACK_NAME)
- **Volumes**: Named as `${STACK_NAME}_purpose` (e.g., bbssr_data)
- **Networks**: Named as `${STACK_NAME}_network_type` (e.g., bbssr_app_network)
- **Services**: Container names follow `${STACK_NAME}_service` (e.g., bbssr_web)

### Configuration Principles

1. **Single Source of Truth**: Configuration lives in stack.env, not in docker-compose files
2. **Portainer Compatibility**: Docker Compose files use syntax compatible with Portainer
3. **Feature Toggles**: Features like PostgreSQL are enabled via environment variables
4. **Default Values**: All environment variables have sensible defaults with `${VAR:-default}` pattern

## Setup for Development

### Prerequisites

- Docker and Docker Compose
- Git
- A code editor (VS Code recommended)

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/backblaze-snapshot-reporting.git
   cd backblaze-snapshot-reporting
   ```

2. **Create your environment file**
   ```bash
   cp stack.env.example stack.env
   ```

3. **Edit the stack.env file with your Backblaze B2 credentials**
   ```bash
   nano stack.env
   ```

4. **Start the application in development mode**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
   ```

5. **Access the application**
   - Open http://localhost:5000 in your web browser

### Environment Variables

All configuration is managed through environment variables in the stack.env file:

1. **Stack Configuration**
   - `STACK_NAME`: Prefix for all Docker resources (default: bbssr)
   - `COMPOSE_PROJECT_NAME`: Project name for Docker Compose (default: bbssr)
   - `PID`: Process ID for the container user (default: 1000)
   - `GID`: Group ID for the container user (default: 1000)

2. **Storage Configuration**
   - `USE_DOCKER_VOLUMES`: Whether to use Docker volumes (true) or local paths (false)
   - `DATA_PATH`: Base path for local data storage (default: ./data)
   - `DATA_VOLUME_NAME`: Name for the data volume (default: bbssr_data)

3. **Database Configuration**
   - `USE_POSTGRES`: Whether to use PostgreSQL (true) or SQLite (false)
   - `POSTGRES_*`: PostgreSQL connection settings

4. **Backblaze Configuration**
   - `B2_APPLICATION_KEY_ID`: Your Backblaze Key ID
   - `B2_APPLICATION_KEY`: Your Backblaze Application Key

## Development Workflow

### Making Code Changes

1. **Start the application in development mode**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
   ```

2. **Edit the code using your preferred editor**
   - The code is automatically reloaded when changes are detected thanks to the Flask debug mode
   - Changes to Python files will be applied without restarting the container
   - HTML template changes will be visible on browser refresh

3. **View real-time logs**
   ```bash
   docker compose logs -f
   ```

### Testing Changes

1. **Run tests within the container**
   ```bash
   docker compose exec web python -m unittest discover -s tests
   ```

2. **Manually test the application**
   - Open http://localhost:5000 in your browser
   - Test specific features like snapshot creation
   - Check API endpoints

### Making Docker Changes

When modifying Docker configuration:

1. **Update docker-compose.yml for service changes**
   - Add new services, networks, or dependencies
   - Always use `${STACK_NAME:-bbssr}` prefix for naming
   - Ensure basic volumes are defined with `{}` only

2. **Update docker-compose.external.yml and docker-compose.local.yml for volume changes**
   - Keep volume definitions synchronized between both files
   - Use `external: true` in external.yml

3. **Update stack.env.example for any new variables**
   - Add sensible defaults
   - Document the purpose of new variables
   - Keep sections organized

4. **Test with both deployment methods**
   ```bash
   # Test local deployment
   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
   
   # Test external deployment
   docker volume create bbssr_data
   docker volume create bbssr_db
   docker compose -f docker-compose.yml -f docker-compose.external.yml up -d
   ```

## Common Docker Commands

```bash
# Start containers with local volumes
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d

# View logs
docker compose logs -f

# Stop containers
docker compose down

# Rebuild and restart
docker compose -f docker-compose.yml -f docker-compose.local.yml build
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d

# Access container shell
docker compose exec web /bin/bash

# View environment variables
docker compose exec web env
```

## Database Management

### SQLite (Default)

The application uses SQLite by default, with the database stored at `/data/backblaze_snapshots.db`.

To access the SQLite database:

```bash
# Enter the container
docker compose exec web /bin/bash

# Access SQLite
sqlite3 /data/backblaze_snapshots.db

# Run queries
SELECT * FROM snapshots LIMIT 5;
.exit
```

### PostgreSQL (Optional)

When using PostgreSQL, configure it through stack.env:

```
USE_POSTGRES=true
POSTGRES_USER=bbssr_user
POSTGRES_PASSWORD=secure_password_here
POSTGRES_DB=bbssr_db
```

To access PostgreSQL:

```bash
# Connect to the PostgreSQL container
docker compose exec postgres psql -U bbssr_user -d bbssr_db

# Run queries
SELECT * FROM snapshots LIMIT 5;
\q
```

## Building for Production

When ready to deploy to production:

1. **Create external volumes**
   ```bash
   docker volume create bbssr_data
   docker volume create bbssr_db
   ```

2. **Deploy with external volumes**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.external.yml up -d
   ```

## Contributing Guidelines

1. Create a new branch for your feature or bug fix
2. Make your changes
3. Ensure Docker compatibility with our standards
4. Test with both volume configurations
5. Submit a pull request with clear documentation

---

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
      - bbssr_data:/data
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
  bbssr_data:
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

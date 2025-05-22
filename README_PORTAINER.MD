# Deploying with Portainer

This guide explains how to deploy the Backblaze Snapshot Reporting application using Portainer.

## Prerequisites

1. Create required directories on the host:
   ```bash
   # Create base directory (adjust path as needed)
   mkdir -p /path/to/data/bbssr_data
   mkdir -p /path/to/data/bbssr_db
   
   # Set permissions (use appropriate UID/GID)
   chown -R 1000:1000 /path/to/data
   ```

## Building the Image

1. In Portainer, navigate to **Images** → **Build Image**

2. Configure the build:
   - **Name**: `bbssr`
   - **Repository URL**: `https://github.com/yourusername/backblaze-snapshot-reporting.git`
   - **Repository reference**: `main` (or your desired branch/tag)
   - **Dockerfile path**: `/Dockerfile`
   - Click **Build the image**

   Note: The image will be built and stored in your Portainer instance's local registry.

## Deploying the Stack

1. Navigate to **Stacks** → **Add stack**

2. Configure the stack:
   - **Name**: `bbssr` (or your preferred stack name)
   - **Repository URL**: `https://github.com/yourusername/backblaze-snapshot-reporting.git`
   - **Repository reference**: `main` (or your desired branch/tag)
   - **Compose path**: Add both files in this order:
     1. `/docker-compose.yml`
     2. `/docker-compose.local.yml`

3. Add environment variables:
   - Copy variables from `stack.env.example` in the repository
   - Set your specific values, especially:
     ```
     STACK_NAME=bbssr
     B2_APPLICATION_KEY_ID=your_key_id
     B2_APPLICATION_KEY=your_application_key
     PID=1000                    # User ID for file ownership (optional)
     GID=1000                    # Group ID for file ownership (optional)
     USE_POSTGRES=1             # Set to 1 if you want to use PostgreSQL
     ```

4. Configure volumes:
   - The following volumes will be created automatically:
     - `bbssr_data`: For application data
     - `bbssr_db`: For PostgreSQL data (if using PostgreSQL)
   - Permissions will be set automatically by the setup service
   - No manual volume creation is needed

5. Deploy the stack:
   - Click **Deploy the stack**
   - The setup service will run first to prepare volumes
   - Then all other services will start automatically

## Service Architecture

The stack includes the following services:
1. `web`: The main application service
2. `postgres`: Database service (if USE_POSTGRES=1)
3. `cloudflared`: Cloudflare tunnel service (if configured)
4. `setup`: Initializes volumes and permissions

## Updating the Stack

To update the running stack:

1. Navigate to your stack in Portainer
2. Click **Update**
3. Select **Pull and redeploy** to get the latest changes
4. Click **Update the stack**

## Monitoring

- View logs: Navigate to the stack → Select a service → Click **Logs**
- Check status: The stack overview shows the status of all services
- Health checks: The application includes health checks that Portainer will monitor

## Troubleshooting

### Common Issues

1. **Image Build Fails**:
   - Check the build logs for errors
   - Ensure all required files are in the repository
   - Verify the Dockerfile path is correct

2. **Stack Won't Deploy**:
   - Verify all required environment variables are set
   - Check that volumes exist and are properly named
   - Look for errors in the service logs

3. **Services Unhealthy**:
   - Check the service logs
   - Verify database configuration (if using PostgreSQL)
   - Ensure Backblaze credentials are correct

### Getting Help

If you encounter issues:
1. Check the application logs in Portainer
2. Refer to the main [README.md](README.md) for general troubleshooting
3. Open an issue in the GitHub repository

## Security Notes

1. Never commit sensitive data to the repository
2. Use Portainer's environment variable management for secrets
3. Consider using Portainer's secret management for sensitive data
4. Regularly update the application and base images

## Backup Considerations

1. Regular volume backups are recommended:
   ```bash
   # Example backup commands (run on host)
   docker run --rm -v bbssr_data:/data -v /backup:/backup \
     alpine tar -czf /backup/bbssr_data.tar.gz /data
   ```

2. Consider implementing automated backup solutions
3. Test restore procedures periodically 
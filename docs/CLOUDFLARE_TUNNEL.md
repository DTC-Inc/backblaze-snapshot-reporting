# Cloudflared Integration

This application supports integration with Cloudflare Tunnels (via cloudflared) to securely expose your application to the internet without opening ports on your firewall.

## Setting Up Cloudflare Tunnel

1. **Create a Cloudflare Account** if you don't have one already at [https://dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up).

2. **Create a Cloudflare Tunnel**:
   - In your Cloudflare dashboard, go to "Teams" > "Access" > "Tunnels".
   - Click "Create a tunnel" and give it a name.
   - Follow the instructions to install the connector (you can skip this as we'll use Docker).
   - Copy the token provided for your tunnel.

3. **Configure Your Application**:
   - Create a `.env` file based on `.env.example` in the root directory of the project.
   - Add your Cloudflare tunnel token to the `.env` file:
     ```
     CLOUDFLARE_TUNNEL_TOKEN=your_tunnel_token_here
     ```
   
4. **Start the Application with Cloudflared**:
   ```bash
   docker-compose --profile with-cloudflared up -d
   ```

## Configuring Public Access

After starting your tunnel, you'll need to configure public access through Cloudflare:

1. Go to your tunnel configuration in the Cloudflare dashboard.
2. Add a public hostname by clicking "Add a public hostname".
3. Configure:
   - Subdomain: choose a subdomain (e.g., `backblaze.yourdomain.com`)
   - Domain: select your domain
   - Path: leave empty or specify a path
   - Service: `web:5000` (this routes traffic to your web app)
   - Save the configuration.

Your Backblaze reporting application should now be securely accessible at the hostname you configured (e.g., `https://backblaze.yourdomain.com`).

## Disabling Cloudflared

If you don't want to use Cloudflare Tunnels, simply:

1. Make sure `CLOUDFLARE_TUNNEL_TOKEN` is not set in your `.env` file (or is empty).
2. Start the application normally:
   ```bash
   docker-compose up -d
   ```

The application will then be accessible directly via port 5000 (or the port specified via `APP_PORT` in your `.env` file).

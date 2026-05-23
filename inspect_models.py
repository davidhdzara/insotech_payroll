import sys
import logging
import os

# Disable Odoo logging to get clean stdout
logging.disable(logging.CRITICAL)

try:
    import odoo
    from odoo.api import Environment
except ImportError:
    print("Could not import odoo")
    sys.exit(1)

# Parse Odoo configuration and override with env variables
config_path = "/home/odoo/.config/odoo/odoo.conf"
odoo.tools.config.parse_config(["-c", config_path])

# Set database configurations explicitly from the environment variables
odoo.tools.config["db_name"] = os.getenv("PGDATABASE")
odoo.tools.config["db_host"] = os.getenv("PGHOST")
odoo.tools.config["db_user"] = os.getenv("PGUSER")
odoo.tools.config["db_password"] = os.getenv("PGPASSWORD")

# Set the addons_path from the Odoo.sh environment variable
if os.getenv("ADDONS_PATH"):
    odoo.tools.config["addons_path"] = os.getenv("ADDONS_PATH")
    
odoo.service.server.load_server_wide_modules()

try:
    db_name = odoo.tools.config["db_name"]
    if not db_name:
        print("Missing database name in environment variables.")
        sys.exit(1)
        
    registry = odoo.registry(db_name)
    with registry.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})
        
        # Search models in registry containing cert, sig, key or signature
        print("=== SEARCHING SECURITY/CERTIFICATE MODELS ===")
        all_models = list(env.registry.models.keys())
        matching_models = [m for m in all_models if "cert" in m or "sig" in m or "key" in m]
        for model_name in sorted(matching_models):
            print(f"  {model_name}")
            
except Exception as e:
    print(f"Error executing Odoo script: {e}")

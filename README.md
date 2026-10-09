# Odoo MCP Server

A flexible MCP (Model Context Protocol) server for Odoo that works with **any database** on your server.  
Switch databases, users, or passwords anytime — just update the environment variables in Claude's connector settings.

---

## 🚀 Deploy on Render

1. Push this folder to a GitHub repo (keep it **private**; never commit credentials)
2. Go to [render.com](https://render.com) → **New → Blueprint** → select the repo. Render reads `render.yaml` and asks for `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`
   - Or use **New → Web Service** manually: Runtime `Python 3`, Build `pip install -r requirements.txt`, Start `python server.py`, then add the four variables under **Environment**
3. Don't set `PORT`; Render provides it
4. After deploy, connect Claude to `https://<your-service>.onrender.com/mcp`

Free plan note: the service sleeps after ~15 minutes without traffic, and the first request then takes about a minute to wake it, so Claude's first tool call may time out. Retry it, or use a paid instance to keep it always on.

To change the database or user: Render → your service → **Environment** → edit the variables → **Save, rebuild, and deploy**.

## 🚀 Deploy on Railway

1. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. Upload or push this folder to a GitHub repo
3. In Railway project settings → **Variables**, add:

| Variable | Example Value |
|---|---|
| `ODOO_URL` | `https://yourodoo.com` |
| `ODOO_DB` | `varnam_weddings` |
| `ODOO_USER` | `admin@varnam.com` |
| `ODOO_PASSWORD` | `your_password_or_api_key` |
| `PORT` | `8000` |

4. Deploy. Railway gives you a public URL like `https://your-app.up.railway.app`

### Odoo Online (odoo.com) databases

- `ODOO_URL` = `https://yourcompany.odoo.com`
- `ODOO_DB` = usually the subdomain (`yourcompany`). If login fails, check the database name in the Odoo database manager on odoo.com (My Databases).
- `ODOO_PASSWORD` = an **API key**: Odoo → avatar → My Profile / Preferences → Account Security → New API Key. Odoo Online users who sign in with their odoo.com account have no local password, so an API key is required.
- Odoo Online allows external API (XML-RPC) access only on the **Custom** pricing plan. On the Standard or One App Free plans, every call will be refused.

---

## 🔌 Connect to Claude.ai

1. Go to **Claude.ai → Settings → Connectors → Add custom connector**
2. Enter your Railway URL: `https://your-app.up.railway.app/mcp`
3. Done! Claude can now use all the tools below.

### Switching Databases

To use a different Odoo database, just update `ODOO_DB` (and optionally `ODOO_USER` / `ODOO_PASSWORD`) in Railway environment variables → redeploy. No code changes needed.

---

## 🛠 Available Tools

| Tool | Description |
|---|---|
| `odoo_get_info` | Get server URL, database, version, logged-in user |
| `odoo_list_databases` | List all databases on the Odoo server |
| `odoo_search_records` | Search any model with domain filters + pagination |
| `odoo_get_record` | Get a single record by ID |
| `odoo_get_fields` | Discover all fields of any model |
| `odoo_create_record` | Create a record in any model |
| `odoo_update_record` | Update a record by ID |
| `odoo_delete_record` | Archive or permanently delete a record |
| `odoo_create_partner` | Create a contact / customer / supplier |
| `odoo_create_crm_lead` | Create a CRM lead or opportunity |
| `odoo_create_sale_order` | Create a sales order with order lines |
| `odoo_get_crm_stages` | List CRM pipeline stages |
| `odoo_get_products` | Search products with optional name filter |
| `odoo_get_customers` | Search customers |
| `odoo_get_invoices` | Search customer invoices |
| `odoo_get_sale_orders` | Search sales orders |
| `odoo_get_purchase_orders` | Search purchase orders |
| `odoo_get_stock` | Check inventory / stock levels |
| `odoo_helpdesk_get_setup` | Helpdesk teams, stages, ticket types, tags, agents (with IDs) |
| `odoo_helpdesk_search_tickets` | Search tickets by text, status, team, stage, agent, customer, priority, type, tag, SLA, date |
| `odoo_helpdesk_get_ticket` | Full ticket: details, SLA status, conversation/chatter, attachments, timesheets |
| `odoo_helpdesk_create_ticket` | Create a ticket |
| `odoo_helpdesk_update_ticket` | Change stage, assignee, team, priority, type, tags, or any field |
| `odoo_helpdesk_post_message` | Post an internal note or email a reply to the customer |
| `odoo_helpdesk_ticket_stats` | Ticket counts grouped by stage / team / agent / priority / month |

---

## 🧪 Local Testing

```bash
pip install -r requirements.txt

export ODOO_URL=https://yourodoo.com
export ODOO_DB=your_db
export ODOO_USER=admin@email.com
export ODOO_PASSWORD=yourpassword

python server.py
# Server runs on http://localhost:8000/mcp
```

---

## 🔐 Security Tips

- Use an **Odoo API key** (Settings → Technical → API Keys) instead of your password
- Create a dedicated Odoo user with minimal permissions for Claude access
- Never commit `.env` files to git

"""
Odoo MCP Server
===============
A flexible MCP server for Odoo that supports dynamic database, user, and password
configuration via environment variables — change them in Claude's connector settings
to switch databases or users at any time.

Environment Variables:
  ODOO_URL      - Odoo server URL (e.g. https://mycompany.odoo.com)
  ODOO_DB       - Database name
  ODOO_USER     - Login username / email
  ODOO_PASSWORD - Password or API key

Deploy on Railway / Render / any Python host, then connect in Claude.ai as a custom MCP.
"""

import html
import json
import os
import re
import xmlrpc.client
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------
mcp = FastMCP("odoo_mcp", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def get_config() -> dict:
    """Read connection config from environment variables."""
    url      = os.environ.get("ODOO_URL", "").rstrip("/")
    db       = os.environ.get("ODOO_DB", "")
    user     = os.environ.get("ODOO_USER", "")
    password = os.environ.get("ODOO_PASSWORD", "")
    if not all([url, db, user, password]):
        raise ValueError(
            "Missing Odoo config. Set ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD "
            "in the connector environment variables."
        )
    return {"url": url, "db": db, "user": user, "password": password}


_uid_cache: dict[tuple, int] = {}
_fields_cache: dict[tuple, set] = {}


def odoo_connect(cfg: dict) -> tuple[int, xmlrpc.client.ServerProxy]:
    """Authenticate (cached per url/db/user/password) and return (uid, models proxy)."""
    key = (cfg["url"], cfg["db"], cfg["user"], cfg["password"])
    uid = _uid_cache.get(key)
    if not uid:
        common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
        uid = common.authenticate(cfg["db"], cfg["user"], cfg["password"], {})
        if not uid:
            raise PermissionError(
                f"Authentication failed for user '{cfg['user']}' on database '{cfg['db']}'. "
                "Check ODOO_USER and ODOO_PASSWORD (on Odoo Online, use an API key)."
            )
        _uid_cache[key] = uid
    models = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")
    return uid, models


def odoo_call(model: str, method: str, domain: list, kwargs: dict | None = None) -> Any:
    """Generic Odoo RPC call with auth from env."""
    cfg = get_config()
    uid, models = odoo_connect(cfg)
    return models.execute_kw(cfg["db"], uid, cfg["password"], model, method, domain, kwargs or {})


def fmt(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def available_fields(model: str, wanted: list[str]) -> list[str]:
    """Keep only the fields that exist on the model (depends on installed apps/version)."""
    cfg = get_config()
    key = (cfg["url"], cfg["db"], model)
    if key not in _fields_cache:
        _fields_cache[key] = set(odoo_call(model, "fields_get", [], {"attributes": ["type"]}))
    return [f for f in wanted if f in _fields_cache[key]]


def html_to_text(value: Any) -> Any:
    """Convert Odoo HTML (descriptions, chatter) to readable plain text."""
    if not value or not isinstance(value, str):
        return value
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    model: str = Field(..., description="Odoo model name, e.g. res.partner, crm.lead, sale.order")
    domain: Optional[str] = Field(default="[]", description='JSON domain filter, e.g. [["name","ilike","John"]]')
    fields: Optional[list[str]] = Field(default=None, description="List of fields to return. Leave empty for defaults.")
    limit: Optional[int] = Field(default=20, ge=1, le=500, description="Max records to return (1-500)")
    offset: Optional[int] = Field(default=0, ge=0, description="Number of records to skip for pagination")

class CreateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    model: str = Field(..., description="Odoo model name, e.g. res.partner")
    values: str = Field(..., description='JSON object of field values, e.g. {"name": "John", "email": "j@x.com"}')

class UpdateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    model: str = Field(..., description="Odoo model name")
    record_id: int = Field(..., description="ID of the record to update")
    values: str = Field(..., description='JSON object of field values to update, e.g. {"phone": "+91 99999 00000"}')

class DeleteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    model: str = Field(..., description="Odoo model name")
    record_id: int = Field(..., description="ID of the record to delete/archive")
    permanent: bool = Field(default=False, description="True to permanently delete; False to archive (set active=False)")

class GetFieldsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    model: str = Field(..., description="Odoo model name, e.g. res.partner")

class PartnerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., description="Contact full name")
    email: Optional[str] = Field(default=None, description="Email address")
    phone: Optional[str] = Field(default=None, description="Phone number")
    mobile: Optional[str] = Field(default=None, description="Mobile number")
    street: Optional[str] = Field(default=None, description="Street address")
    city: Optional[str] = Field(default=None, description="City")
    is_company: bool = Field(default=False, description="True if this is a company")
    customer_rank: int = Field(default=0, description="Set 1 to mark as customer")
    supplier_rank: int = Field(default=0, description="Set 1 to mark as supplier")

class CrmLeadInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., description="Lead/opportunity title")
    partner_name: Optional[str] = Field(default=None, description="Company or customer name")
    contact_name: Optional[str] = Field(default=None, description="Contact person name")
    email_from: Optional[str] = Field(default=None, description="Email address")
    phone: Optional[str] = Field(default=None, description="Phone number")
    mobile: Optional[str] = Field(default=None, description="Mobile number")
    street: Optional[str] = Field(default=None, description="Street address")
    city: Optional[str] = Field(default=None, description="City")
    description: Optional[str] = Field(default=None, description="Internal notes")
    expected_revenue: Optional[float] = Field(default=None, description="Expected revenue")
    probability: Optional[float] = Field(default=None, ge=0, le=100, description="Win probability 0-100")
    priority: Optional[str] = Field(default="0", description="'0' normal, '1' low, '2' high, '3' very high")
    stage_id: Optional[int] = Field(default=None, description="Pipeline stage ID")
    type: str = Field(default="lead", description="'lead' or 'opportunity'")

class SaleOrderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    partner_id: int = Field(..., description="Customer partner ID (use odoo_search_records on res.partner to find)")
    order_lines: Optional[str] = Field(
        default=None,
        description='JSON array of order lines: [{"product_id": 1, "product_uom_qty": 2, "price_unit": 100}]'
    )

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="odoo_get_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_info() -> str:
    """Get current Odoo server info: URL, database name, authenticated user, and server version.

    Returns:
        str: JSON with url, database, user, uid, version info.
    """
    try:
        cfg = get_config()
        common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
        version = common.version()
        uid, _ = odoo_connect(cfg)
        return fmt({
            "url": cfg["url"],
            "database": cfg["db"],
            "user": cfg["user"],
            "uid": uid,
            "server_version": version.get("server_version", "unknown"),
            "server_version_info": version.get("server_version_info", [])
        })
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_list_databases",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_list_databases() -> str:
    """List all available databases on the connected Odoo server.

    Returns:
        str: JSON array of database names available on the server.
    """
    try:
        cfg = get_config()
        db_service = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/db")
        databases = db_service.list()
        return fmt({"databases": databases, "count": len(databases)})
    except Exception as e:
        return fmt({"error": str(e), "hint": "Some Odoo servers disable the DB listing endpoint for security."})


@mcp.tool(
    name="odoo_search_records",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_search_records(params: SearchInput) -> str:
    """Search records in any Odoo model with optional domain filters, field selection, and pagination.

    Args:
        params (SearchInput):
            - model (str): e.g. res.partner, crm.lead, sale.order, product.template
            - domain (str): JSON domain e.g. [["customer_rank",">",0]]
            - fields (list[str]): fields to return; empty = sensible defaults
            - limit (int): max records (default 20)
            - offset (int): skip N records for pagination

    Returns:
        str: JSON with total count, records list, and pagination info.
    """
    try:
        domain = json.loads(params.domain or "[]")
        # Get total count
        total = odoo_call(params.model, "search_count", [domain])
        # Get records
        kwargs: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
        if params.fields:
            kwargs["fields"] = params.fields
        records = odoo_call(params.model, "search_read", [domain], kwargs)
        return fmt({
            "model": params.model,
            "total": total,
            "count": len(records),
            "offset": params.offset,
            "has_more": total > params.offset + len(records),
            "records": records
        })
    except json.JSONDecodeError as e:
        return fmt({"error": f"Invalid domain JSON: {e}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_record",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_record(model: str, record_id: int, fields: Optional[list[str]] = None) -> str:
    """Get a single Odoo record by ID.

    Args:
        model (str): Odoo model name, e.g. res.partner
        record_id (int): Record ID to retrieve
        fields (list[str]): Optional list of fields to return

    Returns:
        str: JSON of the record fields and values.
    """
    try:
        kwargs: dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        result = odoo_call(model, "read", [[record_id]], kwargs)
        if not result:
            return fmt({"error": f"Record {record_id} not found in {model}"})
        return fmt(result[0])
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_fields",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_fields(params: GetFieldsInput) -> str:
    """Get all field definitions for an Odoo model — useful to discover what fields exist and their types.

    Args:
        params (GetFieldsInput):
            - model (str): Odoo model name, e.g. res.partner

    Returns:
        str: JSON dict of field_name → {string, type, required, relation}.
    """
    try:
        fields = odoo_call(params.model, "fields_get", [], {"attributes": ["string", "type", "required", "relation"]})
        # Return sorted for readability
        sorted_fields = dict(sorted(fields.items()))
        return fmt({"model": params.model, "fields": sorted_fields})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_create_record",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
)
async def odoo_create_record(params: CreateInput) -> str:
    """Create a new record in any Odoo model.

    Args:
        params (CreateInput):
            - model (str): Odoo model name, e.g. res.partner
            - values (str): JSON object of field values e.g. {"name": "Test", "email": "t@x.com"}

    Returns:
        str: JSON with new record ID and success message.
    """
    try:
        values = json.loads(params.values)
        new_id = odoo_call(params.model, "create", [values])
        return fmt({"success": True, "id": new_id, "model": params.model, "message": f"Record created with ID {new_id}"})
    except json.JSONDecodeError as e:
        return fmt({"error": f"Invalid values JSON: {e}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_update_record",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_update_record(params: UpdateInput) -> str:
    """Update an existing Odoo record by ID.

    Args:
        params (UpdateInput):
            - model (str): Odoo model name
            - record_id (int): ID of the record to update
            - values (str): JSON object of fields to update e.g. {"phone": "+91 99999 00000"}

    Returns:
        str: JSON with success status.
    """
    try:
        values = json.loads(params.values)
        result = odoo_call(params.model, "write", [[params.record_id], values])
        return fmt({"success": result, "id": params.record_id, "model": params.model, "updated_fields": list(values.keys())})
    except json.JSONDecodeError as e:
        return fmt({"error": f"Invalid values JSON: {e}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_delete_record",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}
)
async def odoo_delete_record(params: DeleteInput) -> str:
    """Delete or archive an Odoo record by ID.

    Args:
        params (DeleteInput):
            - model (str): Odoo model name
            - record_id (int): ID of the record
            - permanent (bool): True = permanent delete; False (default) = archive (active=False)

    Returns:
        str: JSON with success status and action taken.
    """
    try:
        if params.permanent:
            result = odoo_call(params.model, "unlink", [[params.record_id]])
            action = "permanently deleted"
        else:
            result = odoo_call(params.model, "write", [[params.record_id], {"active": False}])
            action = "archived"
        return fmt({"success": result, "id": params.record_id, "action": action})
    except Exception as e:
        return fmt({"error": str(e)})


# ---------------------------------------------------------------------------
# Convenience tools for common Odoo workflows
# ---------------------------------------------------------------------------

@mcp.tool(
    name="odoo_create_partner",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
)
async def odoo_create_partner(params: PartnerInput) -> str:
    """Create a new contact / customer / supplier in Odoo.

    Args:
        params (PartnerInput): Contact details — name, email, phone, city, is_company, etc.

    Returns:
        str: JSON with new partner ID.
    """
    try:
        values: dict[str, Any] = {"name": params.name}
        for f in ["email", "phone", "mobile", "street", "city"]:
            v = getattr(params, f)
            if v is not None:
                values[f] = v
        values["is_company"] = params.is_company
        values["customer_rank"] = params.customer_rank
        values["supplier_rank"] = params.supplier_rank
        new_id = odoo_call("res.partner", "create", [values])
        return fmt({"success": True, "id": new_id, "name": params.name, "message": f"Contact '{params.name}' created with ID {new_id}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_create_crm_lead",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
)
async def odoo_create_crm_lead(params: CrmLeadInput) -> str:
    """Create a new CRM lead or opportunity in Odoo.

    Args:
        params (CrmLeadInput): Lead details — name, contact, email, phone, revenue, stage, etc.

    Returns:
        str: JSON with new lead ID.
    """
    try:
        values: dict[str, Any] = {"name": params.name, "type": params.type}
        optional_fields = ["partner_name", "contact_name", "email_from", "phone", "mobile",
                           "street", "city", "description", "expected_revenue", "probability",
                           "priority", "stage_id"]
        for f in optional_fields:
            v = getattr(params, f)
            if v is not None:
                values[f] = v
        new_id = odoo_call("crm.lead", "create", [values])
        return fmt({"success": True, "id": new_id, "name": params.name, "type": params.type,
                    "message": f"CRM {params.type} '{params.name}' created with ID {new_id}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_create_sale_order",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
)
async def odoo_create_sale_order(params: SaleOrderInput) -> str:
    """Create a new sales order in Odoo for a customer.

    Args:
        params (SaleOrderInput):
            - partner_id (int): Customer ID
            - order_lines (str): JSON array of lines [{"product_id": 1, "product_uom_qty": 2, "price_unit": 100}]

    Returns:
        str: JSON with new sale order ID and name.
    """
    try:
        values: dict[str, Any] = {"partner_id": params.partner_id}
        if params.order_lines:
            lines = json.loads(params.order_lines)
            values["order_line"] = [(0, 0, line) for line in lines]
        new_id = odoo_call("sale.order", "create", [values])
        # Get order name
        record = odoo_call("sale.order", "read", [[new_id]], {"fields": ["name", "state", "amount_total"]})
        order_name = record[0]["name"] if record else str(new_id)
        return fmt({"success": True, "id": new_id, "order_name": order_name,
                    "message": f"Sale order '{order_name}' created with ID {new_id}"})
    except json.JSONDecodeError as e:
        return fmt({"error": f"Invalid order_lines JSON: {e}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_crm_stages",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_crm_stages(limit: int = 50) -> str:
    """List all CRM pipeline stages available in Odoo.

    Args:
        limit (int): Max stages to return (default 50)

    Returns:
        str: JSON list of stages with id, name, and sequence.
    """
    try:
        stages = odoo_call("crm.stage", "search_read", [[]], {"fields": ["id", "name", "sequence"], "limit": limit})
        stages.sort(key=lambda s: s.get("sequence", 999))
        return fmt({"stages": stages, "count": len(stages)})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_products",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_products(name: Optional[str] = None, limit: int = 20) -> str:
    """Search for products in Odoo with optional name filter.

    Args:
        name (str): Optional partial name filter
        limit (int): Max results (default 20)

    Returns:
        str: JSON list of products with id, name, type, list_price, and standard_price.
    """
    try:
        domain: list = []
        if name:
            domain = [["name", "ilike", name]]
        products = odoo_call("product.template", "search_read", [domain], {
            "fields": ["id", "name", "type", "list_price", "standard_price", "categ_id", "default_code"],
            "limit": limit
        })
        return fmt({"products": products, "count": len(products)})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_customers",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_customers(name: Optional[str] = None, limit: int = 20) -> str:
    """Search for customers in Odoo.

    Args:
        name (str): Optional partial name filter
        limit (int): Max results (default 20)

    Returns:
        str: JSON list of customers with id, name, email, phone, city.
    """
    try:
        domain: list = [["customer_rank", ">", 0]]
        if name:
            domain.append(["name", "ilike", name])
        customers = odoo_call("res.partner", "search_read", [domain], {
            "fields": ["id", "name", "email", "phone", "mobile", "city", "street", "customer_rank"],
            "limit": limit
        })
        return fmt({"customers": customers, "count": len(customers)})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_invoices",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_invoices(
    customer_name: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 20
) -> str:
    """Search for customer invoices in Odoo.

    Args:
        customer_name (str): Optional customer name filter
        state (str): Optional state filter — draft, posted, cancel
        limit (int): Max results (default 20)

    Returns:
        str: JSON list of invoices with id, name, partner, amount, state, date.
    """
    try:
        domain: list = [["move_type", "=", "out_invoice"]]
        if state:
            domain.append(["state", "=", state])
        if customer_name:
            domain.append(["partner_id.name", "ilike", customer_name])
        invoices = odoo_call("account.move", "search_read", [domain], {
            "fields": ["id", "name", "partner_id", "amount_total", "state", "invoice_date", "invoice_date_due"],
            "limit": limit,
            "order": "invoice_date desc"
        })
        return fmt({"invoices": invoices, "count": len(invoices)})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_sale_orders",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_sale_orders(
    customer_name: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 20
) -> str:
    """Search for sales orders in Odoo.

    Args:
        customer_name (str): Optional customer name filter
        state (str): Optional state — draft, sent, sale, done, cancel
        limit (int): Max results (default 20)

    Returns:
        str: JSON list of orders with id, name, partner, amount, state, date.
    """
    try:
        domain: list = []
        if state:
            domain.append(["state", "=", state])
        if customer_name:
            domain.append(["partner_id.name", "ilike", customer_name])
        orders = odoo_call("sale.order", "search_read", [domain], {
            "fields": ["id", "name", "partner_id", "amount_total", "state", "date_order"],
            "limit": limit,
            "order": "date_order desc"
        })
        return fmt({"sale_orders": orders, "count": len(orders)})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_purchase_orders",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_purchase_orders(
    supplier_name: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 20
) -> str:
    """Search for purchase orders in Odoo.

    Args:
        supplier_name (str): Optional supplier name filter
        state (str): Optional state — draft, purchase, done, cancel
        limit (int): Max results (default 20)

    Returns:
        str: JSON list of purchase orders.
    """
    try:
        domain: list = []
        if state:
            domain.append(["state", "=", state])
        if supplier_name:
            domain.append(["partner_id.name", "ilike", supplier_name])
        orders = odoo_call("purchase.order", "search_read", [domain], {
            "fields": ["id", "name", "partner_id", "amount_total", "state", "date_order"],
            "limit": limit,
            "order": "date_order desc"
        })
        return fmt({"purchase_orders": orders, "count": len(orders)})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_get_stock",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_get_stock(product_name: Optional[str] = None, limit: int = 20) -> str:
    """Get stock/inventory levels for products in Odoo.

    Args:
        product_name (str): Optional partial product name filter
        limit (int): Max results (default 20)

    Returns:
        str: JSON list of products with qty_available, virtual_available.
    """
    try:
        domain: list = []
        if product_name:
            domain = [["name", "ilike", product_name]]
        products = odoo_call("product.product", "search_read", [domain], {
            "fields": ["id", "name", "default_code", "qty_available", "virtual_available", "uom_id"],
            "limit": limit
        })
        return fmt({"stock": products, "count": len(products)})
    except Exception as e:
        return fmt({"error": str(e)})


# ---------------------------------------------------------------------------
# Helpdesk (Odoo Enterprise) tools
# ---------------------------------------------------------------------------

TICKET_LIST_FIELDS = [
    "id", "ticket_ref", "name", "team_id", "stage_id", "user_id", "partner_id", "partner_name",
    "partner_email", "priority", "ticket_type_id", "tag_ids", "kanban_state", "create_date",
    "close_date", "sla_deadline", "sla_fail",
]

TICKET_DETAIL_FIELDS = TICKET_LIST_FIELDS + [
    "description", "partner_phone", "commercial_partner_id", "company_id", "assign_date",
    "write_date", "sla_reached_late", "rating_last_value", "active", "sale_order_id",
    "total_hours_spent",
]

PRIORITY_HELP = "'0' low, '1' medium, '2' high, '3' urgent"
DATE_HELP = "Date in YYYY-MM-DD format"


def ticket_filter_domain(
    status: str = "all",
    team_id: Optional[int] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
) -> list:
    """Domain parts shared by ticket search and stats. Closed = ticket in a folded stage."""
    domain: list = []
    if status == "open":
        domain.append(["stage_id.fold", "=", False])
    elif status == "closed":
        domain.append(["stage_id.fold", "=", True])
    if team_id:
        domain.append(["team_id", "=", team_id])
    if created_from:
        domain.append(["create_date", ">=", f"{created_from} 00:00:00"])
    if created_to:
        domain.append(["create_date", "<=", f"{created_to} 23:59:59"])
    return domain


class HelpdeskTicketSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    search: Optional[str] = Field(default=None, description="Text to find in ticket subject, reference, or description")
    status: Literal["open", "closed", "all"] = Field(default="open", description="open = not in a folded/closed stage")
    team_id: Optional[int] = Field(default=None, description="Helpdesk team ID (see odoo_helpdesk_get_setup)")
    team: Optional[str] = Field(default=None, description="Partial helpdesk team name")
    stage: Optional[str] = Field(default=None, description="Partial stage name, e.g. 'In Progress'")
    assigned_to: Optional[str] = Field(default=None, description="Partial agent name, or 'unassigned'")
    customer: Optional[str] = Field(default=None, description="Partial customer name or email")
    priority: Optional[str] = Field(default=None, pattern=r"^[0-3]$", description=PRIORITY_HELP)
    ticket_type: Optional[str] = Field(default=None, description="Partial ticket type name")
    tag: Optional[str] = Field(default=None, description="Partial tag name")
    sla_failed: Optional[bool] = Field(default=None, description="True = only tickets that failed an SLA")
    created_from: Optional[str] = Field(default=None, description=DATE_HELP)
    created_to: Optional[str] = Field(default=None, description=DATE_HELP)
    include_archived: bool = Field(default=False, description="Also include archived tickets")
    limit: int = Field(default=20, ge=1, le=500, description="Max tickets to return (1-500)")
    offset: int = Field(default=0, ge=0, description="Number of tickets to skip for pagination")
    order: str = Field(default="create_date desc", description="Sort order, e.g. 'priority desc, create_date asc'")


class HelpdeskTicketInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., description="Ticket subject")
    description: Optional[str] = Field(default=None, description="Ticket description (plain text)")
    team_id: Optional[int] = Field(default=None, description="Helpdesk team ID; Odoo default team if empty")
    partner_id: Optional[int] = Field(default=None, description="Customer partner ID (res.partner)")
    partner_name: Optional[str] = Field(default=None, description="Customer name, if no partner_id")
    partner_email: Optional[str] = Field(default=None, description="Customer email, if no partner_id")
    partner_phone: Optional[str] = Field(default=None, description="Customer phone")
    user_id: Optional[int] = Field(default=None, description="Assigned agent user ID (res.users)")
    priority: Optional[str] = Field(default=None, pattern=r"^[0-3]$", description=PRIORITY_HELP)
    ticket_type_id: Optional[int] = Field(default=None, description="Ticket type ID")
    tag_ids: Optional[list[int]] = Field(default=None, description="Tag IDs")


class HelpdeskTicketUpdateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ticket_id: int = Field(..., description="Ticket ID")
    stage_id: Optional[int] = Field(default=None, description="New stage ID (see odoo_helpdesk_get_setup)")
    user_id: Optional[int] = Field(default=None, description="Assign to this user ID; 0 = unassign")
    team_id: Optional[int] = Field(default=None, description="Move to this helpdesk team ID")
    priority: Optional[str] = Field(default=None, pattern=r"^[0-3]$", description=PRIORITY_HELP)
    ticket_type_id: Optional[int] = Field(default=None, description="Ticket type ID")
    tag_ids: Optional[list[int]] = Field(default=None, description="Replace tags with these tag IDs")
    values: Optional[str] = Field(default=None, description='Extra JSON field values, e.g. {"partner_phone": "+91 ..."}')


class HelpdeskMessageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ticket_id: int = Field(..., description="Ticket ID")
    body: str = Field(..., min_length=1, description="Message text (plain text)")
    message_type: Literal["note", "reply"] = Field(
        default="note",
        description="note = internal log note (not emailed); reply = message emailed to the customer/followers",
    )


class HelpdeskStatsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    group_by: str = Field(
        default="stage_id",
        description="Field to group by: stage_id, team_id, user_id, priority, ticket_type_id, partner_id, "
                    "create_date:month, create_date:week, create_date:day, close_date:month",
    )
    status: Literal["open", "closed", "all"] = Field(default="all", description="Which tickets to count")
    team_id: Optional[int] = Field(default=None, description="Restrict to one helpdesk team ID")
    created_from: Optional[str] = Field(default=None, description=DATE_HELP)
    created_to: Optional[str] = Field(default=None, description=DATE_HELP)


@mcp.tool(
    name="odoo_helpdesk_get_setup",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_helpdesk_get_setup() -> str:
    """Get the Helpdesk configuration: teams, stages, ticket types, tags, and agents (with IDs).

    Call this first to learn the IDs needed for filtering, creating, or updating tickets.

    Returns:
        str: JSON with teams, stages, ticket_types, tags, and agents.
    """
    try:
        result: dict[str, Any] = {}
        teams = odoo_call("helpdesk.team", "search_read", [[]], {
            "fields": available_fields("helpdesk.team", ["id", "name", "member_ids", "use_sla", "use_rating", "company_id"]),
        })
        result["teams"] = teams
        result["stages"] = odoo_call("helpdesk.stage", "search_read", [[]], {
            "fields": available_fields("helpdesk.stage", ["id", "name", "sequence", "fold", "team_ids"]),
            "order": "sequence",
        })
        for key, model in [("ticket_types", "helpdesk.ticket.type"), ("tags", "helpdesk.tag")]:
            try:
                result[key] = odoo_call(model, "search_read", [[]], {"fields": ["id", "name"]})
            except Exception as e:
                result[key] = {"error": str(e)}
        member_ids = sorted({uid for team in teams for uid in team.get("member_ids", [])})
        result["agents"] = odoo_call("res.users", "read", [member_ids], {"fields": ["id", "name", "login"]}) if member_ids else []
        return fmt(result)
    except Exception as e:
        return fmt({"error": str(e), "hint": "Make sure the Helpdesk app is installed and the user has Helpdesk access."})


@mcp.tool(
    name="odoo_helpdesk_search_tickets",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_helpdesk_search_tickets(params: HelpdeskTicketSearchInput) -> str:
    """Search helpdesk tickets by text, status, team, stage, agent, customer, priority, type, tag, SLA, and date.

    Args:
        params (HelpdeskTicketSearchInput): Filters (all optional), limit/offset for pagination, and sort order.

    Returns:
        str: JSON with total count, tickets list, and pagination info.
    """
    try:
        domain = ticket_filter_domain(params.status, params.team_id, params.created_from, params.created_to)
        if params.search:
            text_fields = available_fields("helpdesk.ticket", ["name", "ticket_ref", "description"])
            domain += ["|"] * (len(text_fields) - 1) + [[f, "ilike", params.search] for f in text_fields]
        if params.team:
            domain.append(["team_id.name", "ilike", params.team])
        if params.stage:
            domain.append(["stage_id.name", "ilike", params.stage])
        if params.assigned_to:
            if params.assigned_to.lower() == "unassigned":
                domain.append(["user_id", "=", False])
            else:
                domain.append(["user_id.name", "ilike", params.assigned_to])
        if params.customer:
            domain += ["|", "|",
                       ["partner_id.name", "ilike", params.customer],
                       ["partner_name", "ilike", params.customer],
                       ["partner_email", "ilike", params.customer]]
        if params.priority:
            domain.append(["priority", "=", params.priority])
        if params.ticket_type:
            domain.append(["ticket_type_id.name", "ilike", params.ticket_type])
        if params.tag:
            domain.append(["tag_ids.name", "ilike", params.tag])
        if params.sla_failed is not None:
            domain.append(["sla_fail", "=", params.sla_failed])

        context = {"active_test": False} if params.include_archived else {}
        total = odoo_call("helpdesk.ticket", "search_count", [domain], {"context": context})
        tickets = odoo_call("helpdesk.ticket", "search_read", [domain], {
            "fields": available_fields("helpdesk.ticket", TICKET_LIST_FIELDS),
            "limit": params.limit,
            "offset": params.offset,
            "order": params.order,
            "context": context,
        })
        return fmt({
            "total": total,
            "count": len(tickets),
            "offset": params.offset,
            "has_more": total > params.offset + len(tickets),
            "tickets": tickets,
        })
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_helpdesk_get_ticket",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_helpdesk_get_ticket(ticket_id: int, message_limit: int = 30) -> str:
    """Get one helpdesk ticket in full: details, description, SLA status, conversation history
    (emails, replies, internal notes, stage changes), attachments, and timesheets if installed.

    Args:
        ticket_id (int): Ticket ID
        message_limit (int): Max chatter messages to return, newest first (default 30)

    Returns:
        str: JSON with ticket, sla_status, messages, attachments, and timesheets.
    """
    try:
        context = {"active_test": False}
        records = odoo_call("helpdesk.ticket", "read", [[ticket_id]], {
            "fields": available_fields("helpdesk.ticket", TICKET_DETAIL_FIELDS),
            "context": context,
        })
        if not records:
            return fmt({"error": f"Ticket {ticket_id} not found"})
        ticket = records[0]
        ticket["description"] = html_to_text(ticket.get("description"))
        result: dict[str, Any] = {"ticket": ticket}

        try:
            result["sla_status"] = odoo_call("helpdesk.sla.status", "search_read", [[["ticket_id", "=", ticket_id]]], {
                "fields": ["sla_id", "status", "deadline", "reached_datetime"],
            })
        except Exception:
            result["sla_status"] = []

        messages = odoo_call("mail.message", "search_read", [[
            ["model", "=", "helpdesk.ticket"], ["res_id", "=", ticket_id],
        ]], {
            "fields": ["id", "date", "author_id", "email_from", "message_type", "subtype_id", "subject", "body"],
            "limit": message_limit,
            "order": "date desc, id desc",
        })
        for m in messages:
            m["body"] = html_to_text(m.get("body"))
        result["messages"] = messages

        result["attachments"] = odoo_call("ir.attachment", "search_read", [[
            ["res_model", "=", "helpdesk.ticket"], ["res_id", "=", ticket_id],
        ]], {"fields": ["id", "name", "mimetype", "file_size", "create_date"]})

        if available_fields("account.analytic.line", ["helpdesk_ticket_id"]):
            result["timesheets"] = odoo_call("account.analytic.line", "search_read", [[
                ["helpdesk_ticket_id", "=", ticket_id],
            ]], {"fields": ["date", "employee_id", "name", "unit_amount"], "limit": 100})
        return fmt(result)
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_helpdesk_create_ticket",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
)
async def odoo_helpdesk_create_ticket(params: HelpdeskTicketInput) -> str:
    """Create a new helpdesk ticket.

    Args:
        params (HelpdeskTicketInput): Subject, description, team, customer, agent, priority, type, tags.

    Returns:
        str: JSON with new ticket ID and reference.
    """
    try:
        values: dict[str, Any] = {"name": params.name}
        for f in ["team_id", "partner_id", "partner_name", "partner_email", "partner_phone",
                  "user_id", "priority", "ticket_type_id"]:
            v = getattr(params, f)
            if v is not None:
                values[f] = v
        if params.description:
            values["description"] = html.escape(params.description).replace("\n", "<br/>")
        if params.tag_ids:
            values["tag_ids"] = [(6, 0, params.tag_ids)]
        new_id = odoo_call("helpdesk.ticket", "create", [values])
        record = odoo_call("helpdesk.ticket", "read", [[new_id]], {
            "fields": available_fields("helpdesk.ticket", ["ticket_ref", "team_id", "stage_id", "user_id"]),
        })
        return fmt({"success": True, "id": new_id, **(record[0] if record else {}),
                    "message": f"Ticket '{params.name}' created with ID {new_id}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_helpdesk_update_ticket",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_helpdesk_update_ticket(params: HelpdeskTicketUpdateInput) -> str:
    """Update a helpdesk ticket: change stage (e.g. close/solve it), assign an agent, change team,
    priority, type, tags, or any other field via `values`.

    Args:
        params (HelpdeskTicketUpdateInput): Ticket ID plus the fields to change.

    Returns:
        str: JSON with success status and the updated fields.
    """
    try:
        values: dict[str, Any] = json.loads(params.values) if params.values else {}
        for f in ["stage_id", "team_id", "priority", "ticket_type_id"]:
            v = getattr(params, f)
            if v is not None:
                values[f] = v
        if params.user_id is not None:
            values["user_id"] = params.user_id or False
        if params.tag_ids is not None:
            values["tag_ids"] = [(6, 0, params.tag_ids)]
        if not values:
            return fmt({"error": "Nothing to update — provide at least one field."})
        result = odoo_call("helpdesk.ticket", "write", [[params.ticket_id], values])
        return fmt({"success": result, "id": params.ticket_id, "updated_fields": list(values.keys())})
    except json.JSONDecodeError as e:
        return fmt({"error": f"Invalid values JSON: {e}"})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_helpdesk_post_message",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
)
async def odoo_helpdesk_post_message(params: HelpdeskMessageInput) -> str:
    """Post on a helpdesk ticket's chatter: an internal note, or a reply that is emailed to the customer.

    Args:
        params (HelpdeskMessageInput):
            - ticket_id (int): Ticket ID
            - body (str): Message text
            - message_type (str): 'note' (internal, default) or 'reply' (emailed to customer/followers)

    Returns:
        str: JSON with the new message ID.
    """
    try:
        subtype = "mail.mt_comment" if params.message_type == "reply" else "mail.mt_note"
        message_id = odoo_call("helpdesk.ticket", "message_post", [[params.ticket_id]], {
            "body": html.escape(params.body).replace("\n", "<br/>"),
            "body_is_html": True,
            "message_type": "comment",
            "subtype_xmlid": subtype,
        })
        return fmt({"success": True, "ticket_id": params.ticket_id, "message_id": message_id,
                    "type": params.message_type})
    except Exception as e:
        return fmt({"error": str(e)})


@mcp.tool(
    name="odoo_helpdesk_ticket_stats",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
)
async def odoo_helpdesk_ticket_stats(params: HelpdeskStatsInput) -> str:
    """Count helpdesk tickets grouped by a field — e.g. open tickets per stage, per agent,
    per team, per priority, or tickets created per month.

    Args:
        params (HelpdeskStatsInput): group_by field, status, optional team and creation date range.

    Returns:
        str: JSON with total and a list of {group, count}.
    """
    try:
        domain = ticket_filter_domain(params.status, params.team_id, params.created_from, params.created_to)
        groups = odoo_call("helpdesk.ticket", "read_group", [domain, ["__count"], [params.group_by]], {"lazy": False})
        rows = [{"group": g.get(params.group_by), "count": g.get("__count", 0)} for g in groups]
        return fmt({"group_by": params.group_by, "status": params.status,
                    "total": sum(r["count"] for r in rows), "groups": rows})
    except Exception as e:
        return fmt({"error": str(e)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="streamable-http")

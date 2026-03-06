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

import json
import os
import xmlrpc.client
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------
mcp = FastMCP("odoo_mcp")

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


def odoo_connect(cfg: dict) -> tuple[int, xmlrpc.client.ServerProxy]:
    """Authenticate and return (uid, models proxy)."""
    common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
    uid = common.authenticate(cfg["db"], cfg["user"], cfg["password"], {})
    if not uid:
        raise PermissionError(
            f"Authentication failed for user '{cfg['user']}' on database '{cfg['db']}'. "
            "Check ODOO_USER and ODOO_PASSWORD."
        )
    models = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")
    return uid, models


def odoo_call(model: str, method: str, domain: list, kwargs: dict | None = None) -> Any:
    """Generic Odoo RPC call with auth from env."""
    cfg = get_config()
    uid, models = odoo_connect(cfg)
    return models.execute_kw(cfg["db"], uid, cfg["password"], model, method, domain, kwargs or {})


def fmt(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)

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
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

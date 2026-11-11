"""Unit tests for KakoroPay MCP Server."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from kakoro_mcp.server import create_mcp_server
from kakoro_sdk.ssrf import SSRFSecurityError


@pytest.mark.asyncio
async def test_discover_resources_blocks_ssrf():
    server = create_mcp_server()
    # Call the tool function directly from the server or registry
    # In MCPServer, registered tool can be called directly or via internal dict
    tool_fn = None
    # Let's inspect how the tool is attached
    for tool in getattr(server, "_tools", {}).values():
        if getattr(tool, "name", "") == "discover_resources":
            tool_fn = tool.fn
            break

    if not tool_fn:
        # Check if server._tool_manager or similar exists
        tool_fn = getattr(server, "discover_resources", None)

    # Let's verify SSRF is blocked for loopback without allow_loopback
    with pytest.raises(SSRFSecurityError):
        await server._tool_manager.get_tool("discover_resources").fn("http://127.0.0.1:8000/catalog")


@pytest.mark.asyncio
async def test_discover_resources_success():
    server = create_mcp_server()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"services": ["ai_inference"]}
        mock_get.return_value = mock_resp

        tool = server._tool_manager.get_tool("discover_resources")
        result = await tool.fn("https://example.com/catalog", allow_loopback=False)
        assert result["status"] == "ok"
        assert result["catalog"] == {"services": ["ai_inference"]}


def test_check_budget():
    server = create_mcp_server()
    with patch("kakoro_mcp.server.Web3") as MockW3:
        w3_instance = MagicMock()
        MockW3.return_value = w3_instance
        MockW3.to_checksum_address.side_effect = lambda a: a

        contract = MagicMock()
        w3_instance.eth.contract.return_value = contract
        contract.functions.isSessionActive.return_value.call.return_value = True
        contract.functions.getBudgetRemaining.return_value.call.return_value = (5_000_000, 10, 1800000000)

        tool = server._tool_manager.get_tool("check_budget")
        result = tool.fn(
            account_address="0x" + "1" * 40,
            session_key="0x" + "2" * 40,
        )
        assert result["is_active"] is True
        assert result["remaining_spend_raw"] == 5_000_000
        assert result["remaining_spend_tusd8"] == "5.00 tUSD8"
        assert result["remaining_calls"] == 10

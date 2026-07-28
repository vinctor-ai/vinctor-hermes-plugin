import unittest

from vinctor_hermes_plugin.mcp_discovery import discover_mcp_registry


class McpDiscoveryTests(unittest.TestCase):
    def test_generates_rules_for_unknown_runtime_mcp_tools(self):
        result = discover_mcp_registry(
            {
                "tools": [
                    {"name": "mcp_github_get_me", "description": "Built in GitHub context read"},
                    {"name": "mcp_notion_create_page", "description": "Create a page"},
                    {"tool_name": "mcp_docs_search_pages", "description": "Search pages"},
                    {"toolName": "mcp_linear_delete_issue", "description": "Delete an issue"},
                    {
                        "name": "mcp_release_promote",
                        "description": "Promote a release to production",
                    },
                    {"name": "mcp_unknown_frob", "description": "Do a domain-specific thing"},
                    {"name": "not_mcp_tool", "description": "Ignore me"},
                ]
            }
        )

        self.assertEqual(result.known_builtin, ("mcp_github_get_me",))
        self.assertEqual(
            [rule.as_config_rule() for rule in result.rules],
            [
                {
                    "tool": "mcp_notion_create_page",
                    "matchType": "exact",
                    "pattern": "mcp_notion_create_page",
                    "action": "write",
                    "resource": "mcp/notion/create_page",
                },
                {
                    "tool": "mcp_docs_search_pages",
                    "matchType": "exact",
                    "pattern": "mcp_docs_search_pages",
                    "action": "read",
                    "resource": "mcp/docs/search_pages",
                },
                {
                    "tool": "mcp_linear_delete_issue",
                    "matchType": "exact",
                    "pattern": "mcp_linear_delete_issue",
                    "action": "delete",
                    "resource": "mcp/linear/delete_issue",
                },
                {
                    "tool": "mcp_release_promote",
                    "matchType": "exact",
                    "pattern": "mcp_release_promote",
                    "action": "execute",
                    "resource": "mcp/release/promote",
                },
            ],
        )
        self.assertEqual(
            [(item.name, item.reason) for item in result.skipped],
            [
                ("mcp_unknown_frob", "could_not_infer_action"),
                ("not_mcp_tool", "not_mcp_tool"),
            ],
        )

    def test_accepts_array_registry_and_claude_style_mcp_names(self):
        result = discover_mcp_registry(
            [
                {"name": "mcp__notion_internal__search_pages", "description": "Search pages"},
            ]
        )

        self.assertEqual(
            [rule.as_config_rule() for rule in result.rules],
            [
                {
                    "tool": "mcp__notion_internal__search_pages",
                    "matchType": "exact",
                    "pattern": "mcp__notion_internal__search_pages",
                    "action": "read",
                    "resource": "mcp/notion_internal/search_pages",
                },
            ],
        )

    def test_skips_ambiguous_or_negated_action_inference(self):
        result = discover_mcp_registry(
            {
                "tools": [
                    {"name": "mcp_notion_get_or_create_page"},
                    {
                        "name": "mcp_linear_update_issue",
                        "description": "Post approval comment then merge",
                    },
                    {"name": "mcp_docs_read_policy", "description": "Cannot delete policy records"},
                ]
            }
        )

        self.assertEqual(result.rules, ())
        self.assertEqual(
            [(item.name, item.reason) for item in result.skipped],
            [
                ("mcp_notion_get_or_create_page", "ambiguous_action"),
                ("mcp_linear_update_issue", "ambiguous_action"),
                ("mcp_docs_read_policy", "ambiguous_action"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

NAMED_COLLECTION_KEYS = {
    "actions",
    "attributes",
    "comments",
    "constraints",
    "custom_states",
    "elements",
    "entries",
    "fields",
    "parameters",
    "permissions",
    "privacy_role",
    "states",
    "transitions",
    "values",
    "workflows",
}

EDGE_FIELD_NAMES = {
    "style",
    "element_id",
    "current_parent",
    "api_event",
    "custom_event",
    "action_id",
    "event_id",
    "success_page",
    "failure_page",
    "page",
    "reference",
    "cell_main_axis_id",
}

ENTITY_DOMAINS = {
    "pages": ("page", "pages"),
    "element_definitions": ("component", "components"),
    "mobile_views": ("mobile_view", "mobile_views"),
    "api": ("backend_workflow", "backend_workflows"),
    "user_types": ("user_type", "user_types"),
    "option_sets": ("option_set", "option_sets"),
}

REGISTRY_DOMAINS = {
    "styles": "style",
    "comments": "comment",
}

VIRTUAL_ENTITY_TYPE_FOLDERS = {
    "page_node": "page_nodes",
    "component_node": "component_nodes",
    "mobile_view_node": "mobile_view_nodes",
    "ui_workflow": "ui_workflows",
    "workflow_action": "workflow_actions",
    "backend_workflow_node": "backend_workflow_nodes",
}

VIRTUAL_ENTITY_TYPES = set(VIRTUAL_ENTITY_TYPE_FOLDERS.keys())

INTEGRATION_ENTITY_FOLDERS = {
    "api_connector": "api_connectors",
    "api_connector_call": "api_connector_calls",
    "app_connector": "app_connectors",
    "app_connector_call": "app_connector_calls",
    "plugin_installation": "plugins",
    "plugin_action": "plugin_actions",
}

ROOT_ENTITY_FOLDERS = {
    "application": "applications",
    "app_settings": "app_settings",
}

SYNTHETIC_ENTITY_FOLDERS = {
    "custom_state": "custom_states",
    "field": "fields",
    "option_value": "option_values",
    "event": "events",
    "element_state": "element_states",
    "condition": "conditions",
    "dynamic_expression": "dynamic_expressions",
    "data_source": "data_sources",
}

SYNTHETIC_ENTITY_TYPES = set(SYNTHETIC_ENTITY_FOLDERS.keys())
DEEP_SEARCH_ENTITY_TYPES = VIRTUAL_ENTITY_TYPES | SYNTHETIC_ENTITY_TYPES

EXPRESSION_SOURCE_TYPES = {
    "APIEventParameter",
    "CurrentCell",
    "CurrentDataItem",
    "CurrentDateTime",
    "CurrentOption",
    "CurrentPage",
    "CurrentUser",
    "DoSearch",
    "DoSearchFor",
    "ElementParent",
    "ExternalAPI",
    "GetElement",
    "InjectedValue",
    "PageData",
    "ParentGroup",
    "ParentReusableElement",
    "PreviousStep",
    "SearchBoxValue",
    "ThisElement",
}

EXPRESSION_NON_SOURCE_TYPES = {
    "Message",
    "TextExpression",
    "ListExpression",
    "ArbitraryText",
    "State",
    "Empty",
}

INTEGRATION_REFERENCE_RELATIONS = {
    "api_connector_call",
    "app_connector_call",
    "plugin_action",
    "connector_parent",
    "plugin_installation",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "app",
    "as",
    "at",
    "be",
    "bubble",
    "by",
    "for",
    "from",
    "in",
    "into",
    "io",
    "is",
    "of",
    "on",
    "or",
    "page",
    "the",
    "to",
    "up",
    "with",
}

CAPABILITY_TAXONOMY = {
    "auth": {
        "keywords": [
            "auth",
            "login",
            "log in",
            "sign in",
            "signin",
            "password",
            "reset_pw",
            "reset password",
            "logged in",
            "session",
            "current user",
        ],
        "domains": ["auth"],
        "integrations": [],
    },
    "messaging": {
        "keywords": [
            "message",
            "messages",
            "chat",
            "guest chat",
            "guest_chats",
            "guest_conversations",
            "inbox",
            "thread",
            "conversation",
            "sender",
            "recipient",
        ],
        "domains": ["messaging"],
        "integrations": [],
    },
    "openai": {
        "keywords": [
            "openai",
            "chatgpt",
            "assistant",
            "vector store",
            "vector_store",
            "prompt",
            "prompts",
            "annotation",
            "annotations",
            "run object",
            "run_object",
            "ai",
        ],
        "domains": ["ai"],
        "integrations": ["openai"],
    },
    "reporting": {
        "keywords": [
            "report",
            "daily report",
            "daily_report",
            "kpi",
            "dashboard",
            "summary",
            "analytics",
            "review summary",
        ],
        "domains": ["reporting"],
        "integrations": [],
    },
    "housekeeping": {
        "keywords": [
            "housekeeping",
            "hk",
            "rooms",
            "room",
            "reservation",
            "reservations",
            "upkeep",
            "task",
            "site_housekeepingconfig",
        ],
        "domains": ["operations"],
        "integrations": [],
    },
    "admin": {
        "keywords": [
            "admin",
            "siteadmin",
            "customeradmin",
            "workspace",
            "employee",
            "staff",
            "permissions",
        ],
        "domains": ["admin"],
        "integrations": [],
    },
    "imports": {
        "keywords": [
            "import",
            "sync",
            "integration",
            "mews",
            "mailgun",
            "webhook",
            "csv",
            "download",
            "upload",
        ],
        "domains": ["integrations"],
        "integrations": ["mews", "mailgun"],
    },
    "files": {
        "keywords": [
            "file",
            "files",
            "asset",
            "assets",
            "image",
            "video",
            "media",
            "attachment",
            "attachments",
            "pdf",
        ],
        "domains": ["assets"],
        "integrations": ["files"],
    },
}

QUERY_HINTS = {
    "login functionality": ["auth", "login", "password", "reset_pw", "session"],
    "what is connected to chatgpt/openai": ["openai", "chatgpt", "assistant", "vector store", "prompt"],
    "who uses workflow": ["workflow", "used by", "depends on", "api_event", "custom_event"],
    "guest chat schema": ["guest", "chat", "message", "thread", "schema"],
    "where is custom state visiblegroup used": ["custom state", "visiblegroup", "ui state", "visibility"],
    "why is this element visible": ["element", "visible", "condition", "state", "getelement"],
    "what fields can be modified via api": ["field", "modify api", "data api", "privacy", "auto binding"],
    "what drives this repeating group": ["repeating group", "data source", "search", "current cell"],
    "how is current user used in this flow": ["current user", "condition", "workflow parameter", "data source"],
}

RELATION_WEIGHTS = {
    "workflow_event": 5,
    "api_connector_call": 5,
    "app_connector_call": 5,
    "api_event": 5,
    "custom_event": 5,
    "event_id": 4,
    "connector_parent": 4,
    "workflow_api_exposure": 4,
    "data_api_surface": 4,
    "condition_expression": 4,
    "condition": 4,
    "action_id": 3,
    "element_id": 3,
    "element_state_condition": 3,
    "application_settings": 3,
    "owner_custom_state": 3,
    "defines_field": 3,
    "defines_option_value": 3,
    "element_state": 3,
    "dynamic_expression": 3,
    "expression_data_source": 3,
    "plugin_action": 3,
    "plugin_installation": 3,
    "current_parent": 2,
    "page": 2,
    "success_page": 2,
    "failure_page": 2,
    "style": 1,
    "reference": 1,
    "cell_main_axis_id": 1,
}

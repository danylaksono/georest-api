package httpapi.authz

import rego.v1

test_viewer_cannot_write if {
    not allow with input as {"request_method": "POST", "roles": ["viewer"]}
}

test_editor_can_write if {
    allow with input as {"request_method": "POST", "roles": ["editor"]}
}

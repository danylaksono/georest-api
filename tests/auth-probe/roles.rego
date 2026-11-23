package httpapi.authz

import rego.v1

default allow := false

allow if {
    input.request_method == "GET"
}

allow if {
    input.request_method == "POST"
    "editor" in input.roles
}

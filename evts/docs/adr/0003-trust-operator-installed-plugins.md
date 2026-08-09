# Trust operator-installed plugins

The first release treats plugin code as trusted software installed and upgraded
by an Operator; Administrators may configure and enable installed capabilities
but cannot upload arbitrary code. Sandboxing and an in-product package registry
are deferred because safely executing untrusted extensions would dominate the
first release's security and operational design.

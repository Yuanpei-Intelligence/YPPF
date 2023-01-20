"""
A module for cross app utils, generally some wrappers for library, including:

- hash computation
- logging
- django view class, admin utils
- configurations
- ...

This module should not not depend on any other local modules, except for `boot`.

When adding dependencies between this module and `boot`, be careful.
Make sure no circular reference is ever introduced.

As for now, `boot.config` depends on `utils.config`, while `utils.log` depends on
`boot.settings`. No circular dependency at the fine-grain level.
"""

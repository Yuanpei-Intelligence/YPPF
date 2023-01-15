"""
A module for cross app utils, generally some wrappers for library, including:

- hash computation
- logging
- django view class, admin utils
- configurations
- ...

This module should not not depend on any other local modules. Or, it only depends
on boot, if only necessary. Make sure no circular reference is ever introduced.
As for now, boot only depend on config module, and this module doesn't depend on
boot. Thus, no circular reference.
"""

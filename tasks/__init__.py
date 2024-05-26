from invoke import Collection

from . import (
    kernel,
    rootfs,
    vm,
)

ns = Collection()
ns.add_collection(kernel)
ns.add_collection(rootfs)
ns.add_collection(vm)

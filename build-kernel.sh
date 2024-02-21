#!/bin/bash
set -euxo pipefail

DEFAULT_LINUX_SOURCE="./linux-source"

function download_linux_source() {
    local -r major_version="$1" kernel_version="$2"
    local -r archive="linux.tar.gz"

    mkdir "${DEFAULT_LINUX_SOURCE}"
    pushd "${DEFAULT_LINUX_SOURCE}"
    wget -q -c "https://mirrors.edge.kernel.org/pub/linux/kernel/v"${major_version}".x/linux-"${kernel_version}".tar.gz" -O "${archive}"
    tar -xf "${archive}" --strip-components=1
    popd
}

LINUX_SRC_DIR=""
for i in "$@"; do
    case $i in
        -s=*|--source=*)
            LINUX_SRC_DIR="${i#*=}"
            shift # past argument=value
            ;;
        -t=*|--tag=*)
            TARGET_TAG="${i#*=}"
            shift # past argument=value
            ;;
        -a=*|--arch=*)
            ARCH="${i#*=}"
            shift # past argument=value
            ;;
        --git-source)
            GIT_SOURCE=YES
            shift # past argument with no value
            ;;
        -*|--*)
            echo "Unknown option $i"
            exit 1
            ;;
        *)
            ;;
    esac
done

VERSION=$(echo $TARGET_TAG | cut -d 'v' -f 2)
MAJOR=$(echo $TARGET_TAG | cut -d '.' -f 1 | tr -d 'v')
MINOR=$(echo $TARGET_TAG | cut -d '.' -f 2)


if [ "${LINUX_SRC_DIR}" == "" ]; then
    download_linux_source $MAJOR $VERSION
fi

exit 0

# Copy extra config to source directory
cp ./extra.config $LINUX_SRC_DIR/extra.config
# Build kernel
make -C $LINUX_SRC_DIR clean
make -C $LINUX_SRC_DIR ARCH=$ARCH KCONFIG_CONFIG=start.config defconfig
tee -a < $LINUX_SRC_DIR/extra.config $LINUX_SRC_DIR/start.config
make -C $LINUX_SRC_DIR allnoconfig KCONFIG_ALLCONFIG=start.config
if [[ "$ARCH" == "arm64" && $MAJOR -eq 4 && $MINOR -lt 9 ]]; then echo "kvm_guest.config target not available for $ARCH $TARGET_TAG"; else make -C $LINUX_SRC_DIR kvm_guest.config; fi
make -j$(nproc) -C $LINUX_SRC_DIR ARCH=$ARCH bindeb-pkg LOCALVERSION=-ddvm
mkdir kernel-$TARGET_TAG.$ARCH.pkg
cp $LINUX_SRC_DIR/arch/$ARCH/boot/$BZ_IMAGE kernel-$TARGET_TAG.$ARCH.pkg/bzImage
cp $LINUX_SRC_DIR/vmlinux kernel-$TARGET_TAG.$ARCH.pkg/vmlinux
find $LINUX_SRC_DIR/.. -name "linux-headers-$(echo $TARGET_TAG | tr -d 'v')*" -type f | xargs -i cp {} kernel-$TARGET_TAG.$ARCH.pkg/
find $LINUX_SRC_DIR/.. -name "linux-image-$(echo $TARGET_TAG | tr -d 'v')*" -type f | grep -Fv dbg | xargs -i cp {} kernel-$TARGET_TAG.$ARCH.pkg/

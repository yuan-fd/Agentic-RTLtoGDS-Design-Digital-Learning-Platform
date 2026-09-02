from __future__ import annotations

import platform

import pytest

from openroad_platform_contracts import PluginManifest
from openroad_platform_contracts.product_surface import DEFAULT_PRODUCT_SURFACE, ProductRole


def _manifest(plugin_id: str, capabilities: tuple[str, ...]) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id, plugin_version="1.0.0", adapter_entry=("adapter",),
        capabilities=capabilities, supported_arch=(platform.machine(),),
        input_schema={"type": "object"}, output_schema={"type": "object"},
    )


def test_product_surface_allows_only_approved_identity_and_capability():
    DEFAULT_PRODUCT_SURFACE.authorize(
        ProductRole.RTL_GENERATION,
        _manifest("rtlscout", ("agent.rtl.generate",)),
    )
    DEFAULT_PRODUCT_SURFACE.authorize(
        ProductRole.L2_OPTIMIZATION,
        _manifest("orfs-agent", ("optimizer.l2.propose",)),
    )


def test_product_surface_rejects_registered_but_non_product_algorithms():
    with pytest.raises(PermissionError, match="not approved"):
        DEFAULT_PRODUCT_SURFACE.authorize(
            ProductRole.L2_OPTIMIZATION,
            _manifest("local-bo", ("optimizer.l2.propose",)),
        )
    with pytest.raises(PermissionError, match="not approved"):
        DEFAULT_PRODUCT_SURFACE.authorize(
            ProductRole.L2_OPTIMIZATION,
            _manifest("unknown-plugin", ("optimizer.l2.propose",)),
        )
    with pytest.raises(PermissionError, match="lacks approved capability"):
        DEFAULT_PRODUCT_SURFACE.authorize(
            ProductRole.L2_OPTIMIZATION,
            _manifest("orfs-agent", ("optimizer.l2.dataset-bridge",)),
        )


def test_taiwei_is_an_explicit_independent_extension_role():
    DEFAULT_PRODUCT_SURFACE.authorize(
        ProductRole.INDEPENDENT_3D,
        _manifest("taiwei-pin-3d", ("eda.3d.pin3d",)),
    )
    assert DEFAULT_PRODUCT_SURFACE.rule_for(ProductRole.INDEPENDENT_3D).role.value == \
        "extension.independent_3d"

"""Stable allowlist for the approved product capability surface.

This contract is intentionally smaller than :class:`PluginRegistry`: the
registry knows every installed manifest, whereas this module states which
identity/capability pair may serve a named product role.  Research and
extension manifests remain registrable but cannot become a product default by
being present in the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .platform import PluginManifest


class ProductRole(str, Enum):
    RTL_GENERATION = "product.rtl_generation"
    L2_OPTIMIZATION = "product.l2_optimization"
    OPENROAD_KNOWLEDGE = "product.openroad_knowledge"
    INDEPENDENT_3D = "extension.independent_3d"


@dataclass(frozen=True)
class ProductCapabilityRule:
    """One approved manifest identity and capability for a public role."""

    role: ProductRole
    plugin_id: str
    capability: str

    def validate(self) -> None:
        if not self.plugin_id or not self.capability:
            raise ValueError("product capability rule requires plugin_id and capability")


class ProductSurface:
    """Dependency-free, explicit product-role allowlist.

    A caller must ask for a role; resolving an installed plugin by name alone
    is deliberately insufficient for a product path.  This makes local
    research optimizers and unadmitted extensions ineligible by default.
    """

    def __init__(self, rules: tuple[ProductCapabilityRule, ...]):
        if not rules:
            raise ValueError("product surface requires at least one rule")
        self._rules = {rule.role: rule for rule in rules}
        if len(self._rules) != len(rules):
            raise ValueError("product surface role may appear only once")
        for rule in rules:
            rule.validate()

    def rule_for(self, role: ProductRole) -> ProductCapabilityRule:
        try:
            return self._rules[ProductRole(role)]
        except (KeyError, ValueError) as exc:
            raise LookupError(f"product role is not enabled: {role}") from exc

    def authorize(self, role: ProductRole, manifest: PluginManifest) -> None:
        manifest.validate()
        rule = self.rule_for(role)
        if manifest.plugin_id != rule.plugin_id:
            raise PermissionError(
                f"{manifest.plugin_id} is not approved for product role {rule.role.value}"
            )
        if rule.capability not in manifest.capabilities:
            raise PermissionError(
                f"{manifest.plugin_id} lacks approved capability {rule.capability}"
            )

    def rules(self) -> tuple[ProductCapabilityRule, ...]:
        return tuple(self._rules[role] for role in ProductRole if role in self._rules)


DEFAULT_PRODUCT_SURFACE = ProductSurface((
    ProductCapabilityRule(ProductRole.RTL_GENERATION, "rtlscout", "agent.rtl.generate"),
    ProductCapabilityRule(ProductRole.L2_OPTIMIZATION, "a2-orfo",
                          "optimizer.l2.a2-orfo-feedback"),
    ProductCapabilityRule(ProductRole.OPENROAD_KNOWLEDGE, "orassistant",
                          "knowledge.openroad.retrieve"),
    ProductCapabilityRule(ProductRole.INDEPENDENT_3D, "taiwei-pin-3d", "eda.3d.pin3d"),
))

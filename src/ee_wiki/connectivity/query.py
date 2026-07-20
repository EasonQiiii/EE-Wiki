"""Query schematic connectivity sidecars for net / pin / module traces."""

from __future__ import annotations

from dataclasses import dataclass, field

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.connectivity.authority import (
    AuthorityPolicy,
    annotate_module_nets,
    apply_authority_gate,
)
from ee_wiki.connectivity.store import (
    ConnectivityDocument,
    load_connectivity_documents,
)
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope

LIMITATIONS = (
    "Connectivity traces come from ingested *.connectivity.json sidecars "
    "(netlist / boardview / PDF geometry / OCR). Evidence tags are not "
    "board-verified copper; prefer cad_netlist > boardview > pdf_geometry > "
    "ocr_spatial when sources disagree."
)


@dataclass
class ConnectivityQuery:
    """Read-only queries over loaded connectivity documents.

    The raw ``trace_net`` / ``connector_pins`` / ``module_nets`` methods return
    unfiltered sidecar data. Answer-grade consumers (chat, MCP, HTTP, FA) must
    instead call :meth:`resolve_trace`, which enforces the authoritative-only
    gate (:mod:`ee_wiki.connectivity.authority`) so advisory geometry/OCR
    connectivity can never be presented as a verified trace.
    """

    documents: list[ConnectivityDocument]
    layout: DataLayoutConfig
    scope_inheritance: bool = True
    authority: AuthorityPolicy = field(default_factory=AuthorityPolicy)

    def resolve_trace(
        self,
        kind: str,
        query: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        source_file: str | None = None,
        page: int | None = None,
    ) -> dict:
        """Answer-grade trace, gated by the authoritative-only policy.

        This is the single choke point every consumer (chat trace intercept,
        MCP tools, HTTP routes, future FA auto-trace) must use so that
        connectivity conclusions are only ever grounded on board-verified
        evidence (CAD netlist / BoardView).

        Args:
            kind: ``"net"`` (trace a net), ``"pins"`` (a connector/part), or
                ``"module"`` (page module zone locator).
            query: Net name, designator, or module label.
            product: Optional product filter.
            project: Optional project filter.
            build: Optional build filter.
            source_file: Optional substring filter on schematic/sidecar path.
            page: Optional 1-based page filter (``module`` only).

        Returns:
            A gated result dict with ``authoritative`` / ``authority`` flags.
            For ``net`` / ``pins`` under an authority requirement, advisory-only
            data yields ``found=False`` and a refusal ``note``. ``module`` is
            always annotated as advisory (locator, not verified trace).

        Raises:
            ValueError: If ``kind`` is not one of ``net`` / ``pins`` / ``module``.
        """
        if kind == "net":
            raw = self.trace_net(
                query,
                product=product,
                project=project,
                build=build,
                source_file=source_file,
            )
            return apply_authority_gate(raw, self.authority)
        if kind == "pins":
            raw = self.connector_pins(
                query,
                product=product,
                project=project,
                build=build,
                source_file=source_file,
            )
            return apply_authority_gate(raw, self.authority)
        if kind == "module":
            raw = self.module_nets(
                query,
                product=product,
                project=project,
                build=build,
                source_file=source_file,
                page=page,
            )
            return annotate_module_nets(raw, self.authority)
        raise ValueError(f"Unknown trace kind: {kind!r}")

    def _scoped_docs(
        self,
        *,
        product: str | None,
        project: str | None,
        build: str | None,
        source_file: str | None = None,
    ) -> list[ConnectivityDocument]:
        if product is None and project is None and build is None:
            docs = list(self.documents)
        elif self.scope_inheritance and product and project and build:
            allowed = set(
                expand_retrieval_scope(product, project, build, self.layout)
            )
            docs = [
                d
                for d in self.documents
                if (d.product, d.project, d.build) in allowed
            ]
        else:
            docs = [
                d
                for d in self.documents
                if (product is None or d.product == product)
                and (project is None or d.project == project)
                and (build is None or d.build == build)
            ]
        if source_file:
            needle = source_file.strip().lower()
            docs = [
                d
                for d in docs
                if needle in d.source_file.lower()
                or needle in str(d.sidecar_path).lower()
            ]
        return docs

    def trace_net(
        self,
        net: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        source_file: str | None = None,
    ) -> dict:
        """Return all pin bindings on ``net`` across matching sidecars.

        Args:
            net: Net name to look up (case-insensitive exact match preferred,
                then substring).
            product: Optional product filter.
            project: Optional project filter.
            build: Optional build filter.
            source_file: Optional substring filter on schematic/sidecar path.

        Returns:
            Result dict with ``found``, ``pins``, ``documents``, ``limitations``.
        """
        token = net.strip()
        if not token:
            return {
                "query": net,
                "kind": "trace_net",
                "found": False,
                "error": "net query is empty",
                "pins": [],
                "documents": [],
                "limitations": LIMITATIONS,
            }

        docs = self._scoped_docs(
            product=product, project=project, build=build, source_file=source_file
        )
        exact: list[dict] = []
        fuzzy: list[dict] = []
        matched_docs: list[dict] = []
        token_upper = token.upper()

        for doc in docs:
            nets = doc.connectivity.nets
            hit_keys = [k for k in nets if k.upper() == token_upper]
            if not hit_keys:
                hit_keys = [k for k in nets if token_upper in k.upper()]
                bucket = fuzzy
            else:
                bucket = exact
            if not hit_keys:
                continue
            matched_docs.append(_doc_summary(doc))
            for key in sorted(hit_keys):
                for binding in nets[key]:
                    bucket.append(
                        {
                            "net": key,
                            "refdes": binding.refdes,
                            "pin": binding.pin,
                            "evidence": binding.evidence,
                            "product": doc.product,
                            "project": doc.project,
                            "build": doc.build,
                            "source_file": doc.source_file,
                            "sidecar_path": str(doc.sidecar_path),
                        }
                    )

        pins = exact if exact else fuzzy
        resolved = pins[0]["net"] if pins else None
        return {
            "query": net,
            "kind": "trace_net",
            "resolved_net": resolved,
            "found": bool(pins),
            "match": "exact" if exact else ("substring" if fuzzy else None),
            "product": product,
            "project": project,
            "build": build,
            "pins": pins,
            "pin_count": len(pins),
            "documents": matched_docs,
            "limitations": LIMITATIONS,
        }

    def connector_pins(
        self,
        refdes: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        source_file: str | None = None,
    ) -> dict:
        """Return pin↔net list for a designator (connector or any part).

        Also attaches page-level connector catchment metadata when present.
        """
        token = refdes.strip()
        if not token:
            return {
                "query": refdes,
                "kind": "connector_pins",
                "found": False,
                "error": "refdes query is empty",
                "pins": [],
                "connectors": [],
                "documents": [],
                "limitations": LIMITATIONS,
            }

        docs = self._scoped_docs(
            product=product, project=project, build=build, source_file=source_file
        )
        exact_pins: list[dict] = []
        fuzzy_pins: list[dict] = []
        connectors: list[dict] = []
        matched_docs: list[dict] = []
        token_upper = token.upper()

        for doc in docs:
            parts = doc.connectivity.parts
            hit_keys = [k for k in parts if k.upper() == token_upper]
            if not hit_keys:
                hit_keys = [k for k in parts if token_upper in k.upper()]
                pin_bucket = fuzzy_pins
            else:
                pin_bucket = exact_pins

            page_hits = []
            for page in doc.connectivity.pages:
                for connector in page.connectors:
                    if (
                        connector.refdes.upper() == token_upper
                        or token_upper in connector.refdes.upper()
                    ):
                        page_hits.append(
                            {
                                "refdes": connector.refdes,
                                "module": connector.module,
                                "nets": list(connector.nets),
                                "evidence": connector.evidence,
                                "page": page.page,
                                "product": doc.product,
                                "project": doc.project,
                                "build": doc.build,
                                "source_file": doc.source_file,
                                "sidecar_path": str(doc.sidecar_path),
                            }
                        )

            if not hit_keys and not page_hits:
                continue
            matched_docs.append(_doc_summary(doc))
            for key in sorted(hit_keys):
                for binding in parts[key]:
                    pin_bucket.append(
                        {
                            "refdes": key,
                            "pin": binding.pin,
                            "net": binding.net,
                            "evidence": binding.evidence,
                            "product": doc.product,
                            "project": doc.project,
                            "build": doc.build,
                            "source_file": doc.source_file,
                            "sidecar_path": str(doc.sidecar_path),
                        }
                    )
            connectors.extend(page_hits)

        pins = exact_pins if exact_pins else fuzzy_pins
        resolved = None
        if pins:
            resolved = pins[0]["refdes"]
        elif connectors:
            resolved = connectors[0]["refdes"]
        return {
            "query": refdes,
            "kind": "connector_pins",
            "resolved_refdes": resolved,
            "found": bool(pins or connectors),
            "match": "exact" if exact_pins else ("substring" if fuzzy_pins else None),
            "product": product,
            "project": project,
            "build": build,
            "pins": pins,
            "pin_count": len(pins),
            "connectors": connectors,
            "documents": matched_docs,
            "limitations": LIMITATIONS,
        }

    def module_nets(
        self,
        module: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        source_file: str | None = None,
        page: int | None = None,
    ) -> dict:
        """Return nets associated with a page module zone label."""
        token = module.strip()
        if not token:
            return {
                "query": module,
                "kind": "module_nets",
                "found": False,
                "error": "module query is empty",
                "modules": [],
                "documents": [],
                "limitations": LIMITATIONS,
            }

        docs = self._scoped_docs(
            product=product, project=project, build=build, source_file=source_file
        )
        modules: list[dict] = []
        matched_docs: list[dict] = []
        token_upper = token.upper()

        for doc in docs:
            doc_hits: list[dict] = []
            for page_conn in doc.connectivity.pages:
                if page is not None and page_conn.page != page:
                    continue
                for label, nets in page_conn.module_nets.items():
                    if label.upper() == token_upper or token_upper in label.upper():
                        doc_hits.append(
                            {
                                "module": label,
                                "nets": list(nets),
                                "page": page_conn.page,
                                "evidence": page_conn.source,
                                "product": doc.product,
                                "project": doc.project,
                                "build": doc.build,
                                "source_file": doc.source_file,
                                "sidecar_path": str(doc.sidecar_path),
                            }
                        )
            if doc_hits:
                matched_docs.append(_doc_summary(doc))
                modules.extend(doc_hits)

        return {
            "query": module,
            "kind": "module_nets",
            "found": bool(modules),
            "product": product,
            "project": project,
            "build": build,
            "page": page,
            "modules": modules,
            "documents": matched_docs,
            "limitations": LIMITATIONS,
        }


def _doc_summary(doc: ConnectivityDocument) -> dict:
    return {
        "product": doc.product,
        "project": doc.project,
        "build": doc.build,
        "source_file": doc.source_file,
        "sidecar_path": str(doc.sidecar_path),
        "sources_used": list(doc.connectivity.sources_used),
        "companions": doc.connectivity.companions.to_dict(),
        "schema_version": doc.connectivity.schema_version,
    }


def open_connectivity_query(
    *,
    processed_dir,
    layout: DataLayoutConfig,
    scope_inheritance: bool = True,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    authority: AuthorityPolicy | None = None,
) -> ConnectivityQuery:
    """Load sidecars and return a :class:`ConnectivityQuery`.

    Args:
        processed_dir: ``data/processed/`` root.
        layout: Data layout config.
        scope_inheritance: Whether queries expand to common/global.
        product: Optional preload filter.
        project: Optional preload filter.
        build: Optional preload filter.
        authority: Authoritative-only trace policy. Defaults to the safe policy
            (CAD netlist / BoardView required) when omitted.

    Returns:
        Query handle (may have zero documents).
    """
    documents = load_connectivity_documents(
        processed_dir,
        layout,
        product=product,
        project=project,
        build=build,
    )
    return ConnectivityQuery(
        documents=documents,
        layout=layout,
        scope_inheritance=scope_inheritance,
        authority=authority or AuthorityPolicy(),
    )

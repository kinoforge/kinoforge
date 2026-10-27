"""Flow segment: a canvas of connected nodes the caller runs one node at a time.

Kinoforge owns the node catalog (ports, config schemas), the graph check (types, cycles,
required inputs) and each node's run. The caller stores flows, runs the nodes in the order
the check gives, keeps their outputs, and bills."""

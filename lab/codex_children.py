"""Lifecycle evidence for children spawned by the owned Codex app-server."""


class NativeChildren:
    def __init__(self):
        self.threads = {}
        self.errors = []

    def discover(self, child, parent):
        state = self.threads.setdefault(child, {
            "parent_thread_id": parent, "spawn_observed": False,
            "turns": {}, "tokens": [0, 0, 0], "position": 0})
        if state["parent_thread_id"] != parent:
            self.errors.append(child + ": conflicting parent identity")
        return state

    def observe(self, message, parents):
        method = message.get("method")
        params = message.get("params", {})
        thread = params.get("threadId")
        item = params.get("item", {})
        if (method in ("item/started", "item/completed")
                and item.get("type") == "subAgentActivity" and item.get("kind") == "started"
                and (thread in parents or thread in self.threads)):
            child = item.get("agentThreadId")
            if not isinstance(child, str) or not child or child == thread or child in parents:
                self.errors.append("invalid native child identity")
                return
            self.discover(child, thread)["spawn_observed"] = True
        state = self.threads.get(thread)
        if state is None:
            return
        state["position"] += 1
        turn_id = params.get("turnId") or params.get("turn", {}).get("id")
        if method == "turn/started":
            if not isinstance(turn_id, str) or not turn_id:
                self.errors.append(thread + ": child turn has no identity")
                return
            state["turns"].setdefault(turn_id, {
                "status": "inProgress", "before": state["tokens"][:],
                "tokens": state["tokens"][:], "activity_at": 0, "price_at": 0})
        turn = state["turns"].get(turn_id)
        if method == "error" and params.get("willRetry") is not True:
            self.errors.append(thread + ": native child provider error")
        if turn is None:
            if method in ("turn/completed", "thread/tokenUsage/updated"):
                self.errors.append(thread + ": child event has no owned turn start")
            return
        if ((method in ("item/started", "item/completed")
                and item.get("type") in ("reasoning", "agentMessage"))
                or method == "item/agentMessage/delta"):
            turn["activity_at"] = state["position"]
        elif method == "thread/tokenUsage/updated":
            total = params.get("tokenUsage", {}).get("total", {})
            tokens = [total.get(key, 0) for key in ("inputTokens", "outputTokens", "cachedInputTokens")]
            if (all(type(n) is int and n >= 0 for n in tokens)
                    and tokens[2] <= tokens[0]
                    and all(a >= b for a, b in zip(tokens, state["tokens"]))):
                if tokens[:2] != state["tokens"][:2]:
                    turn["price_at"] = state["position"]
                turn["tokens"] = state["tokens"] = tokens
            else:
                self.errors.append(thread + ": child counters invalid or decreased")
        elif method == "turn/completed":
            turn["status"] = params["turn"].get("status")
            if turn["status"] != "completed" or params["turn"].get("error"):
                self.errors.append(thread + ": native child turn did not complete successfully")

    def report(self, readers, model, effort, *, allow_model_variation=False):
        errors, pending = list(self.errors), []
        active = False
        for thread, state in self.threads.items():
            reader = readers.get(thread)
            turns = state["turns"]
            if not state["spawn_observed"]:
                active = True
                pending.append(thread + ": waiting for owned spawn notification")
            if not turns:
                active = True
                pending.append(thread + ": waiting for child turn")
            if reader is None or not reader.validated:
                pending.append(thread + ": waiting for owned child history")
            if reader is not None:
                errors.extend(thread + ": " + e for e in reader.errors)
                own_turns = set(reader.turn_contexts) | {r["turn_id"] for r in reader.responses.values()}
                for turn_id in sorted(own_turns - turns.keys()):
                    active = True
                    pending.append(thread + ": " + turn_id + " is waiting for lifecycle notifications")
                errors.extend(thread + ": child model/effort differs from admission"
                    for ctx in reader.turn_contexts.values()
                    if not allow_model_variation and (ctx.get("model"), ctx.get("effort")) != (model, effort))
                if reader.plans & {"api", "unknown"}:
                    errors.append(thread + ": child does not report a recognized subscription plan")
                if not reader.plans:
                    pending.append(thread + ": waiting for child subscription evidence")
                if reader.missing_compactions:
                    pending.append(thread + ": missing child compaction receipts")
            for turn_id, turn in turns.items():
                if turn["status"] == "inProgress":
                    active = True
                    pending.append(thread + ": " + turn_id + " is active")
                elif turn["status"] != "completed":
                    pending.append(thread + ": " + turn_id + " did not complete")
                receipts = ([r for key, r in reader.responses.items()
                             if r["turn_id"] == turn_id and key not in reader.compactions]
                            if reader else [])
                needed = [a - b for a, b in zip(turn["tokens"], turn["before"])]
                covered = [sum(r["usage"][i] for r in receipts) for i in range(3)]
                if (reader is None or turn_id not in reader.turn_contexts or not receipts
                        or sum(needed[:2]) <= 0 or turn["price_at"] < turn["activity_at"]
                        or any(a < b for a, b in zip(covered, needed))):
                    pending.append(thread + ": " + turn_id + " has incomplete usage coverage")
        return {"threads": self.threads, "errors": sorted(set(errors)), "pending": pending,
                "active": active, "measurement_complete": not errors and not pending}

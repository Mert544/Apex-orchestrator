class BudgetController:
    def __init__(self, max_total_nodes: int) -> None:
        self.max_total_nodes = max_total_nodes
        self.used_nodes = 0

    @property
    def exhausted(self) -> bool:
        return self.used_nodes >= self.max_total_nodes

    def consume_node(self) -> None:
        self.used_nodes += 1

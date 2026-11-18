from notification_service_v3.template import Template


class TemplateRegistry:
    """Every template the service knows, by id. Ids are unique."""

    def __init__(self) -> None:
        self._templates: dict[str, Template] = {}

    def register(self, template: Template | None) -> None:
        if template is None:
            raise ValueError("No template given")
        if template.id in self._templates:
            raise ValueError(f"Duplicate template {template.id}")
        self._templates[template.id] = template

    def template(self, id: str | None) -> Template:
        t = None if id is None else self._templates.get(id.strip())
        if t is None:
            raise ValueError(f"No template {id}")
        return t

    def templates(self) -> list[Template]:
        return list(self._templates.values())

"""Route unmanaged Gutenberg catalog tables to the Postgres alias."""

GUTENBERG = {"mirror", "robotblock", "job"}


class GutenbergRouter:
    def db_for_read(self, model, **hints):
        if model._meta.model_name in GUTENBERG:
            return "gutenberg"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.model_name in GUTENBERG:
            return "gutenberg"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        names = {obj1._meta.model_name, obj2._meta.model_name}
        if names & GUTENBERG:
            return names <= GUTENBERG
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if model_name in GUTENBERG or hints.get("model_name") in GUTENBERG:
            return False
        if db == "gutenberg":
            return False
        return None

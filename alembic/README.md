Use Alembic from [backend](/abs/path/backend) after installing requirements:

```powershell
alembic revision --autogenerate -m "initial hostel erp schema"
alembic upgrade head
```

The env file loads `app.config.settings.database_url`, so Railway MySQL works when the standard Railway variables are present.

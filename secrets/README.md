# Local Secrets

Create `secrets/tws_password.txt` containing only the Interactive Brokers password and
restrict it before starting the gateway:

```sh
chmod 600 secrets/tws_password.txt
```

The directory is ignored by Git. Do not commit credentials.
# DiZp K8S mutating webhook

## Generate certs

`ca.cnf`

```ini
[ req ]
default_bits       = 4096
prompt             = no
default_md         = sha256
distinguished_name = req_distinguished_name
x509_extensions    = v3_ca

[ req_distinguished_name ]
CN = frico-ca-admission

[ v3_ca ]
subjectAltName = @alt_names
basicConstraints = critical,CA:TRUE
keyUsage = critical, digitalSignature, cRLSign, keyCertSign

[alt_names]
DNS.1 = frico-webhook
DNS.2 = frico-webhook.frico
DNS.3 = frico-webhook.frico.svc
```

`cert.cnf`

```ini
[ req ]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = req_distinguished_name
req_extensions     = req_ext

[ req_distinguished_name ]
CN = frico-webhook.frico.svc

[ req_ext ]
subjectAltName = @alt_names

[alt_names]
DNS.1 = frico-webhook
DNS.2 = frico-webhook.frico
DNS.3 = frico-webhook.frico.svc
```

```bash
openssl req -new -x509 -sha256 -days 3650 -key keys/ca.key -out keys/ca.crt -extensions v3_ca -config ca.cnf
openssl x509 -in keys/ca.crt -text -noout
```

```bash
openssl req -new -nodes -out keys/mycert.csr -newkey rsa:2048 -keyout keys/mycert.key -config cert.cnf
openssl x509 -req -in keys/mycert.csr -CA keys/ca.crt -CAkey keys/ca.key -CAcreateserial -out keys/mycert.crt -days 365 -extensions req_ext -extfile cert.cnf
```

```bash
cat ca.crt | base64
kubectl -n frico create secret tls frico-webhook-certs --cert=mycert.crt --key=mycert.key 
```

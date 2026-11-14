# Software bill of materials and compliance

## SBOM

| Release | Components |
|---|---|
| RTOS REL-RTOS | RTOS kernel & driver open-source package (BSD / Apache), safety-certified compiler seat, code signing |
| OS REL-OS | Linux kernel & user-space package (GPL / LGPL / MIT), code signing |
| Cloud REL-CLOUD | Linux package, cloud-native package (Apache-2.0), code signing |
| Digital factory REL-MES | Web & database package, commercial database middleware license, code signing |
| Robot software REL-ROBOT | RTOS components, robotics middleware & vision libraries, safety compiler, code signing |

Open-source components cost 0, but not nothing: each one passes a **license review** and a **vulnerability review** before entering the repository — the software company's incoming inspection.
The open-source "supplier" passes about 97 %: roughly one component in thirty has an unsuitable license (e.g. GPL linked into closed code) or an unfixed high-severity vulnerability and is sent back for another version.

## Licenses and subscriptions

Licenses (RTOS, OS, robot software) are one per device, issued by the license server; subscriptions (cloud, digital factory) are provisioned on a host and then accepted by the monitoring platform over 24 hours.
In the system they are finished goods without physical stock: issuing one uses one license-key quota.

## Also needed for products in China (described here, not filed)

- **Multi-Level Protection Scheme 2.0 (MLPS 2.0)**: the cloud at level 3 — authentication, access control, audit, intrusion prevention, backup; assessed yearly.
- **Software copyright registration**: once per product and major version.
- **Open-source license compliance**: ship the component list and license texts with every release.
- **Data export**: Chinese customers' data stays in data centers in China.

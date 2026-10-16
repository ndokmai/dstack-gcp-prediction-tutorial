# SEC 304 Assignment 3: Confidential Computing with Intel TDX

Build a small prediction service, protect its communication with TLS, and deploy it inside an Intel TDX confidential virtual machine on Google Cloud. Finally, verify the server's attestation evidence locally before sending private data.

The assignment develops one application across four modules. Each introduces a new layer while preserving the prediction API, so you can understand and test the pieces separately before combining them.

## The application

Three roles participate:

- **Server:** runs a simple linear model using Python, Flask, and Gunicorn. It starts without model weights.
- **Model owner:** uploads synthetic coefficients representing private model weights. The server accepts only a file matching the SHA-256 hash embedded in its code.
- **Prediction client:** sends property features and receives a predicted price. It does not receive the model file or independently check the weights.

The model is deliberately small so the focus stays on deployment and trust. Synthetic coefficients represent private data, but the example is not suitable for real property valuations. Repeated predictions can reveal a linear model's coefficients; confidential execution does not prevent that kind of inference.

## Module directory and table of contents

Follow the modules in order. Each directory contains its own tutorial README and the files needed for that stage, with one deliberate dependency: module 3 reuses module 2's application and TLS identity.

| Module                           | Tutorial                                                                                        | What you build and learn                                                                                                                                                                                             |
| -------------------------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Build the server**          | [Build a prediction server: from local Python to local Docker](1_Build_Server_Docker/README.md) | Run the server, model owner, and client using separate uv projects. Check model provisioning and prediction over HTTP, then build and run the server in local Docker.                                                |
| **2. Add TLS**                   | [Add HTTPS without rewriting the application](2_TLS_Transport/README.md)                        | Generate a TLS identity, distribute trusted public certificate copies, and supply the private key as a runtime Docker secret. Authenticate the server and encrypt communication.                                     |
| **3. Deploy to Intel TDX**       | [Deploy the existing HTTPS server to an Intel TDX VM](3_Deploy_TDX/README.md)                   | Publish the unchanged TLS image to Docker Hub, pin its digest, configure dstack OS on GCP, and deliver the existing private key through Secret Manager. Test the remote service without caller-side attestation yet. |
| **4. Verify remote attestation** | [Authenticate a TDX server with RA-TLS](4_Remote_Attestation/README.md)                         | Request a fresh TLS identity inside the guest. Use a local Rust verifier to check Intel TDX and Google vTPM evidence against approved deployment policy before either caller sends private inputs.                   |

**Start here: [Module 1](1_Build_Server_Docker/README.md).**

## How the pieces fit together

Docker packages the server code, Python runtime, and dependencies. Docker Hub distributes that application image by digest. The dstack guest OS boots inside a GCP Intel TDX VM and launches the container. The model owner and prediction client remain outside the VM.

In the final module, the dstack guest agent issues a fresh key and an attestation-bearing TLS certificate through `/GetTlsKey`. Each caller receives the certificate during TLS and checks its embedded evidence locally, using Intel and Google verification material and an independently approved policy. That policy contains the UKI boot executable's Authenticode hash and the generated application configuration's Compose hash, which commits to the pinned Docker image reference.

Only after verification succeeds does the caller send model weights or prediction features over the same TLS connection.

## What each stage establishes

- **Module 1:** the application works and can run in a container. Plain HTTP does not protect secrets.
- **Module 2:** the endpoint possesses the private key matching the trusted certificate, and TLS protects data in transit. This does not identify the running code.
- **Module 3:** the operator deploys the application on a VM configured for TDX. The callers still trust the operator and pre-generated TLS identity.
- **Module 4:** each caller authenticates the measured deployment and its TLS key under the verifier's Intel/Google trust assumptions and approved policy. Attestation does not prove that the application is bug-free.

## Before you begin

You should be comfortable with basic Python, a terminal, and the idea of public/private keys. Each module explains its tools and installation requirements where they become necessary:

- **Modules 1–2:** uv, Docker, and then OpenSSL. No cloud account is required.
- **Modules 3–4:** a Docker Hub account, a billing-enabled GCP project with Intel TDX quota/capacity, Google Cloud CLI, and disk-packaging tools.
- **Module 4:** Rust for building the local verifier. Caller computers do not need TDX hardware.

The tutorials include macOS and Ubuntu/Debian paths. Follow only the commands labeled for your operating system, especially the GNU tar setup for GCP deployment on macOS.

Generate your own certificates and keys when instructed. Keep private keys and generated deployment files out of Git. Cloud resources incur charges: follow each cloud module's cleanup instructions when finished, including checks for leftover disks, images, and storage buckets.

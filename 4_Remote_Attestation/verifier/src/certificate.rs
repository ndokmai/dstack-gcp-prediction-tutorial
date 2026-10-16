// SPDX-License-Identifier: Apache-2.0
//! Extract dstack RA-TLS evidence and bind it to the leaf's actual SPKI.
//! Adapted from upstream ra-tls/src/attestation.rs and QuoteContentType::RaTlsCert.
use anyhow::{ensure, Context, Result};
use sha2::{Digest, Sha512};
use x509_parser::prelude::*;

fn extension_bytes(value: &[u8]) -> Result<Vec<u8>> {
    // x509-parser removes X.509's outer extnValue OCTET STRING. dstack adds
    // another DER OCTET STRING inside it (ra-tls/src/traits.rs). Remove exactly
    // that wrapper before interpreting the SCALE V0 data.
    let (remaining, octets) = x509_parser::der_parser::der::parse_der_octetstring(value)
        .map_err(|e| anyhow::anyhow!("invalid dstack extension wrapper: {e}"))?;
    ensure!(remaining.is_empty(), "trailing dstack extension bytes");
    Ok(octets
        .as_slice()
        .context("expected extension octets")?
        .to_vec())
}

pub fn extract(der: &[u8]) -> Result<(crate::evidence::Attestation, [u8; 64])> {
    let (remaining, cert) =
        parse_x509_certificate(der).map_err(|e| anyhow::anyhow!("invalid certificate: {e}"))?;
    ensure!(remaining.is_empty(), "trailing certificate bytes");
    ensure!(
        cert.validity().is_valid(),
        "certificate expired or not yet valid"
    );
    let extensions: Vec<_> = cert
        .extensions()
        .iter()
        .filter(|e| e.oid.to_id_string() == "1.3.6.1.4.1.62397.1.8")
        .collect();
    ensure!(
        extensions.len() == 1,
        "expected exactly one dstack attestation extension"
    );
    let bytes = extension_bytes(extensions.first().context("missing attestation")?.value)?;
    let attestation = crate::evidence::decode(&bytes)?;
    // Bind the full DER SubjectPublicKeyInfo from the certificate.
    let mut hash = Sha512::new();
    hash.update(b"ratls-cert:");
    hash.update(cert.public_key().raw);
    Ok((attestation, hash.finalize().into()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unwraps_dstack_extension_before_evidence_decode() {
        assert_eq!(extension_bytes(&[4, 3, 0, 1, 7]).unwrap(), [0, 1, 7]);
        // Certificates containing real quotes use DER's long-form length.
        let mut value = vec![4, 0x82, 1, 0];
        value.extend_from_slice(&[0; 256]);
        assert_eq!(extension_bytes(&value).unwrap(), [0; 256]);
    }

    #[test]
    fn malformed_or_trailing_extension_rejects() {
        for value in [&[4, 2, 0][..], &[4, 1, 0, 1][..], &[2, 1, 0][..]] {
            assert!(extension_bytes(value).is_err());
        }
    }

    #[test]
    fn malformed_certificate_rejects() {
        assert!(extract(b"not a certificate").is_err());
    }

    #[test]
    fn ordinary_certificate_without_evidence_rejects() {
        // Public production Google root: a valid certificate is not RA-TLS proof.
        let (_, pem) = x509_parser::pem::parse_x509_pem(include_bytes!(
            "../vendor/tpm-qvl/certs/gcp-root-ca.pem"
        ))
        .unwrap();
        let error = extract(&pem.contents).err().unwrap().to_string();
        assert!(error.contains("attestation extension"), "{error}");
    }
}

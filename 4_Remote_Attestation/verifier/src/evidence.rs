// SPDX-FileCopyrightText: © 2024-2025 Phala Network <dstack@phala.network>
// SPDX-License-Identifier: Apache-2.0
//! GCP-only projection of dstack-attest's SCALE V0 schema.
//! Derived from the pinned upstream types listed in the module README.
//! Explicit codec indices preserve wire compatibility after removing variants.
//! This module parses evidence; it does not authenticate any of its fields.

use anyhow::{ensure, Context, Result};
use cc_eventlog::{RuntimeEvent, TdxEvent};
use scale::{Decode, Encode};
use tpm_types::TpmQuote;

#[derive(Clone, Encode, Decode)]
pub struct TdxQuote {
    pub quote: Vec<u8>,
    pub event_log: Vec<TdxEvent>,
}

#[derive(Clone, Encode, Decode)]
pub struct GcpQuote {
    pub tdx_quote: TdxQuote,
    pub tpm_quote: TpmQuote,
}

#[derive(Clone, Encode, Decode)]
pub enum AttestationQuote {
    // Upstream GCP is variant 1, not 0. All other platform tags reject.
    #[codec(index = 1)]
    GcpTdx(GcpQuote),
}

#[derive(Clone, Encode, Decode)]
pub struct Attestation {
    pub quote: AttestationQuote,
    pub runtime_events: Vec<RuntimeEvent>,
    pub report_data: [u8; 64],
    pub config: String,
    pub report: (),
}

#[derive(Clone, Encode, Decode)]
enum VersionedAttestation {
    #[codec(index = 0)]
    V0 { attestation: Attestation },
}

pub fn decode(bytes: &[u8]) -> Result<Attestation> {
    ensure!(bytes.len() <= 10 * 1024 * 1024, "evidence exceeds 10 MiB");
    let mut input = bytes;
    let VersionedAttestation::V0 { attestation } = VersionedAttestation::decode(&mut input)
        .context("expected SCALE V0 GCP-TDX evidence; other platforms are unsupported")?;
    ensure!(input.is_empty(), "trailing bytes after evidence");
    Ok(attestation)
}

#[cfg(test)]
pub(crate) mod tests {
    #[test]
    fn preserves_gcp_wire_tags_and_rejects_trailing_bytes() {
        use super::*;
        let quote = TpmQuote {
            message: vec![],
            signature: vec![],
            pcr_values: vec![],
            ak_cert: vec![],
            platform: dstack_types::Platform::Gcp,
            event_log: vec![],
        };
        let input = VersionedAttestation::V0 {
            attestation: Attestation {
                quote: AttestationQuote::GcpTdx(GcpQuote {
                    tdx_quote: TdxQuote {
                        quote: vec![],
                        event_log: vec![],
                    },
                    tpm_quote: quote,
                }),
                runtime_events: vec![],
                report_data: [7; 64],
                config: "{}".into(),
                report: (),
            },
        };
        let mut bytes = input.encode();
        assert_eq!(&bytes[..2], &[0, 1]);
        assert_eq!(decode(&bytes).unwrap().report_data, [7; 64]);
        assert!(decode(&bytes[..bytes.len() - 1]).is_err());
        bytes.push(0);
        assert!(decode(&bytes).is_err());
    }

    #[test]
    fn rejects_other_platforms_and_versions() {
        for tag in [0, 2, 3, 4] {
            assert!(super::decode(&[0, tag]).is_err());
        }
        assert!(super::decode(&[1, 1]).is_err());
        assert!(super::decode(&[]).is_err());
        assert!(super::decode(&vec![0; 10 * 1024 * 1024 + 1]).is_err());
    }
}

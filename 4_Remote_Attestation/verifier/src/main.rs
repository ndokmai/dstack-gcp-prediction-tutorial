// SPDX-License-Identifier: Apache-2.0
//! Local verifier CLI: no deployment, guest devices, or secret handling.
//! Supply the live TLS leaf certificate plus trusted local policy.
//! Rejection prints an error, exits nonzero, and never emits an acceptance verdict.

mod certificate;
mod evidence;
mod verification;

use anyhow::{ensure, Context, Result};
use serde::Deserialize;
use std::{path::Path, time::Duration};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    compose_hash: String,
    uki_authenticode_sha256: String,
}

fn fixed_hex<const N: usize>(value: &str) -> Result<[u8; N]> {
    hex::decode(value.trim())?
        .try_into()
        .map_err(|_| anyhow::anyhow!("expected {N} bytes"))
}

fn bounded_read(path: &Path) -> Result<Vec<u8>> {
    use std::io::Read;
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(22 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 22 * 1024 * 1024, "input too large");
    Ok(bytes)
}

#[tokio::main]
async fn main() -> Result<()> {
    let mut args: Vec<_> = std::env::args().skip(1).collect();
    let debug = args.last().is_some_and(|arg| arg == "--debug");
    if debug {
        args.pop();
    }
    ensure!(
        args.len() == 2,
        "usage: sec304-tdx-verifier CERTIFICATE.der POLICY.json [--debug]"
    );
    let policy: Policy = serde_json::from_slice(&bounded_read(Path::new(&args[1]))?)?;
    let der = bounded_read(Path::new(&args[0]))?;
    let (attestation, expected_report) = certificate::extract(&der)?;
    if debug {
        let evidence::AttestationQuote::GcpTdx(gcp) = &attestation.quote;
        eprintln!(
            "[RA-TLS] Certificate parsed and extension unwrapped. Received evidence (UNVERIFIED):"
        );
        // Public wire evidence, not application bodies, keys or arbitrary config.
        eprintln!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "tdx_quote_hex": hex::encode(&gcp.tdx_quote.quote),
                "tdx_event_log": &gcp.tdx_quote.event_log,
                "tpm_attestation_hex": hex::encode(&gcp.tpm_quote.message),
                "tpm_signature_hex": hex::encode(&gcp.tpm_quote.signature),
                "tpm_pcr_values": &gcp.tpm_quote.pcr_values,
                "tpm_event_log": &gcp.tpm_quote.event_log,
                "runtime_events": &attestation.runtime_events,
                "report_data": hex::encode(attestation.report_data),
            }))?
        );
    }
    // A global deadline makes unavailable collateral a rejection, not a bypass.
    let result = tokio::time::timeout(
        Duration::from_secs(120),
        verification::verify(
            attestation,
            &fixed_hex::<32>(&policy.compose_hash)?,
            &fixed_hex::<32>(&policy.uki_authenticode_sha256)?,
            &expected_report,
            debug,
        ),
    )
    .await
    .context("collateral/verification deadline exceeded")??;
    // The caller confirms that this verdict refers to its exact live certificate.
    use sha2::{Digest, Sha256};
    let mut output = serde_json::to_value(result)?;
    output["certificate_sha256"] = hex::encode(Sha256::digest(&der)).into();
    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}

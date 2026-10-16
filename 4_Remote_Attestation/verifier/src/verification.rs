// SPDX-FileCopyrightText: © 2024-2025 Phala Network <dstack@phala.network>
// SPDX-License-Identifier: Apache-2.0
//! GCP branch adapted from upstream dstack-attest and dstack-verifier.
//! Intel/Google signature, chain, revocation and PCR checks stay in their QVLs.
//! Unlike full CvmVerifier, this narrow adapter takes the approved UKI hash
//! directly from a trusted local release file. It does not trust config.os_image_hash.

use anyhow::{ensure, Context, Result};
use cc_eventlog::replay_events;
use dcap_qvl::{collateral::CollateralClient, quote::Report};
use dstack_types::Platform;
use ez_hash::{Sha256, Sha384};
use hex_literal::hex;
use serde::Serialize;
use sha2::{Digest, Sha256 as Hash256};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::evidence::{Attestation, AttestationQuote};

#[derive(Serialize)]
pub struct VerifiedClaims {
    pub is_valid: bool,
    pub tee_variant: &'static str,
    pub tcb_status: String,
    pub compose_hash: String,
    pub uki_authenticode_sha256: String,
    pub report_data: String,
}

// Only events emitted before system-ready count as trusted launch policy.
fn compose_hash(attestation: &Attestation) -> Result<Vec<u8>> {
    let events = &attestation.runtime_events;
    ensure!(
        events.iter().any(|e| e.event == "system-ready"),
        "missing system-ready event"
    );
    let values: Vec<_> = events
        .iter()
        .take_while(|e| e.event != "system-ready")
        .filter(|e| e.event == "compose-hash")
        .collect();
    ensure!(
        values.len() == 1,
        "expected exactly one boot-time compose-hash event"
    );
    ensure!(
        values[0].payload.len() == 32,
        "compose hash must be 32 bytes"
    );
    Ok(values[0].payload.clone())
}

pub async fn verify(
    attestation: Attestation,
    approved_compose: &[u8; 32],
    approved_uki: &[u8; 32],
    expected_report: &[u8; 64],
    debug: bool,
) -> Result<VerifiedClaims> {
    let progress = |message: &str| {
        if debug {
            eprintln!("[RA-TLS verifier] {message}");
        }
    };
    let AttestationQuote::GcpTdx(gcp) = &attestation.quote;
    ensure!(
        gcp.tpm_quote.platform == Platform::Gcp,
        "expected Google vTPM evidence"
    );

    // Collateral delivery is not the trust anchor: use the production Intel root.
    progress("Fetch Intel collateral and verify quote signature / security status.");
    let collateral = CollateralClient::with_default_http(dcap_qvl::collateral::PHALA_PCCS_URL)?
        .fetch(&gcp.tdx_quote.quote)
        .await?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let tdx = dcap_qvl::verify::QuoteVerifier::new_prod().verify(
        &gcp.tdx_quote.quote,
        &collateral,
        now,
    )?;
    let td = match &tdx.report {
        Report::TD10(report) => report,
        Report::TD15(report) => {
            ensure!(report.mr_service_td == [0; 48], "unexpected service TD");
            &report.base
        }
        _ => anyhow::bail!("expected a TDX report, not SGX"),
    };
    // Preserve upstream TDX attribute checks; additionally enforce our strict policy.
    ensure!(td.td_attributes[0] & 1 == 0, "debug TD rejected");
    ensure!(td.mr_signer_seam == [0; 48], "unexpected SEAM signer");
    ensure!(
        tdx.status == "UpToDate",
        "TCB status is not UpToDate: {}",
        tdx.status
    );
    progress("Intel quote accepted. Check certificate public-key binding.");
    ensure!(
        td.report_data == *expected_report,
        "RA-TLS certificate public-key binding mismatch"
    );
    ensure!(
        attestation.report_data == *expected_report,
        "envelope report_data mismatch"
    );

    // Recompute chained event measurements, not program execution.
    progress("Recompute runtime events and compare with TDX RTMR3.");
    let runtime384 = replay_events::<Sha384>(&attestation.runtime_events, None);
    ensure!(
        runtime384 == td.rt_mr3,
        "runtime event log does not match TDX RTMR3"
    );
    cc_eventlog::tdx::validate_v2_preimages(&gcp.tdx_quote.event_log)?;

    // The Google root is embedded in the vendored tpm-qvl source.
    progress("Fetch Google collateral and verify TPM signature / boot event log.");
    let tpm = tpm_qvl::QuoteVerifier::new_prod(Platform::Gcp)?
        .fetch_and_verify(&gcp.tpm_quote)
        .await?;
    ensure!(
        tpm.attest.qualified_data == Hash256::digest(&gcp.tdx_quote.quote).as_slice(),
        "Google quote is not bound to this Intel quote"
    );
    progress("Check TPM-to-TDX quote binding and runtime events against PCR14.");
    let runtime256 = replay_events::<Sha256>(&attestation.runtime_events, None);
    ensure!(
        tpm.get_pcr(14)? == runtime256.as_slice(),
        "runtime log does not match TPM PCR14"
    );

    // Upstream GCP OVMF v2 / PCR2 event layout, preserved for this pinned guest.
    progress("Check approved firmware PCR0 and UKI measurement in PCR2.");
    const EXPECTED_PCR0: [u8; 32] =
        hex!("0cca9ec161b09288802e5a112255d21340ed5b797f5fe29cecccfd8f67b9f802");
    ensure!(
        tpm.get_pcr(0)? == EXPECTED_PCR0,
        "unexpected Google boot firmware PCR0"
    );
    let pcr2_events: Vec<_> = tpm.event_log.iter().filter(|e| e.pcr_index == 2).collect();
    let uki_event = pcr2_events
        .get(2)
        .context("missing GCP UKI event in PCR2")?;
    ensure!(
        uki_event.digest.as_slice() == approved_uki,
        "booted UKI is not the approved release"
    );

    // A genuine quote is insufficient: approve the measured application configuration.
    progress("Check boot-time Compose hash against trusted local policy.");
    let compose = compose_hash(&attestation)?;
    ensure!(
        compose.as_slice() == approved_compose,
        "unapproved application Compose hash"
    );
    progress("All required verifier checks passed.");
    Ok(VerifiedClaims {
        is_valid: true,
        tee_variant: "dstack-gcp-tdx",
        tcb_status: tdx.status,
        compose_hash: hex::encode(compose),
        uki_authenticode_sha256: hex::encode(approved_uki),
        report_data: hex::encode(expected_report),
    })
}

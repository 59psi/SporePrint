# Monocypher 4.0.3 (vendored)

Ed25519 signature verification for signed node OTA manifests
(`lib/sp_core/ota_manifest.h`). It lives inside `sp_core` (compiled with it,
and shipped with it, licence included, in every Builder ZIP) rather than as
its own library.

| | |
|---|---|
| Upstream | https://monocypher.org, https://github.com/LoupVaillant/Monocypher |
| Release | 4.0.3 (2026-06-15), `monocypher-4.0.3.tar.gz`; git tag `4.0.3` = commit `ab2b16dd619ad5f6979a4fbe69cfa324a6fcc35f` |
| Tarball SHA-512 | `40904ada5c7ee4f7741733e38b69a30a4b0561cbffba5ffe7c2dce16136d540251ec0d9056ff606510d3b5b708fb8a40db7e0870d4a0b2dc17ba2bfb880f8965` (the published `.sha512`) |
| Tarball SHA-256 | `8cc9bc341a66249016db9bd70e9142d8d0aef9945973744b1ac05dbc55d8ee66` |
| Licence | BSD-2-Clause or CC0-1.0, your choice (`LICENCE.md`, complete) |
| Verified | 2026-10-06: the monocypher.org and GitHub-release tarballs are byte-identical, and every file below is byte-identical to the tarball's |

Vendored, **unmodified**: `src/monocypher.{c,h}`, `src/optional/monocypher-ed25519.{c,h}`
and `LICENCE.md`. Nothing else is needed (the tests, docs, makefile,
`monocypher.pc` and `change-prefix.sh` stay upstream). Against the git tag the
release files differ only where upstream's release script makes them differ:
line 1 is stamped `4.0.3` instead of `__git__`, and `LICENCE.md` drops the
"Special notes" paragraph about `tests/externals/`, which the tarball does
not ship.

| File | SHA-256 |
|---|---|
| `monocypher.c` | `57eb914fc88136119bd41655cccb8c250048bf54d470540625186f8ab16f64be` |
| `monocypher.h` | `c494da712122da7ff679fdcf318a5317e84972b6c950fe9d896212947797facd` |
| `monocypher-ed25519.c` | `60fce3578fb00b00da96490653d993c4cb427b1e1be38183285c66e04d22cc18` |
| `monocypher-ed25519.h` | `abc4fad381879f5c29176ebe014b9189956b3dfe0a3e36459b6990bc57212380` |
| `LICENCE.md` | `5f8360e4c06ddcc584bdb4b210c6af824c4bb301e6a9a521869b6d90795ca4b3` |

`server/tests/test_firmware_vendor.py` holds the tree to this table and checks
that the Builder ZIPs carry these files; `.gitattributes` turns off line-ending
conversion so every checkout stays byte-identical.

## What the firmware uses

- **`crypto_ed25519_check(sig, pubkey, msg, len)`** only: pure Ed25519 with
  SHA-512 (RFC 8032), not the `_ph` pre-hash variant, over exactly the
  canonical manifest bytes, with the key compiled in at build time
  (`SPOREPRINT_OTA_PUBKEY_B64`, `sp_device/ota_build.h`). It returns 0 for a
  valid signature and -1 otherwise, and it refuses a non-canonical S (S ≥ L),
  as the Pi's verifier does, so a malleated signature cannot verify on one
  side and fail on the other. Monocypher does no input validation, so
  `sp_device/ota_service.cpp` only calls it with a decoded signature of
  exactly 64 bytes and a decoded key of exactly 32.
- **Timing.** Verification handles only public data (the manifest, its
  signature, the pinned key), so it does not need to run in constant time.
  The 4.0.3 fix ("timing leak in EdDSA/Ed25519 signatures": compilers could
  turn `fe_ccopy` / `fe_cswap` into secret-dependent code) protects the
  signing path, which no device image links.
- **API.** 4.0.3 marks nothing deprecated. The 3.x calls (`crypto_sign`,
  `crypto_check`, the incremental sign/check API) were removed in 4.0.0, and
  the firmware uses none of them.
- **Linked code.** In a device image `--gc-sections` keeps
  `crypto_ed25519_check`, `crypto_eddsa_check_equation`,
  `crypto_eddsa_reduce`, `crypto_sha512_{init,update,final}`,
  `crypto_verify32` and `crypto_wipe`, with their static helpers
  (`nm firmware.elf`, `node_esp32` and `cam_esp32s3`, 2026-10-06). No signing,
  X25519, ChaCha20, BLAKE2b or Argon2 code is linked. Only the native tests
  call `crypto_ed25519_key_pair` / `crypto_ed25519_sign`, to sign test
  manifests with the test-only key in `test/fixtures/ota_manifest_vectors.json`.

`test_core_ota_manifest` checks it against RFC 8032 §7.1 tests 1-3, a
malleated S + L signature, and every case in the shared manifest vectors.

## Upgrading

```sh
v=4.0.3   # the new release
curl -LO https://monocypher.org/download/monocypher-$v.tar.gz
curl -LO https://monocypher.org/download/monocypher-$v.tar.gz.sha512
shasum -a 512 monocypher-$v.tar.gz; cat monocypher-$v.tar.gz.sha512  # must match
tar xzf monocypher-$v.tar.gz
cp monocypher-$v/src/monocypher.[ch] monocypher-$v/src/optional/monocypher-ed25519.[ch] \
   monocypher-$v/LICENCE.md firmware/lib/sp_core/vendor/monocypher/
shasum -a 256 firmware/lib/sp_core/vendor/monocypher/*.[ch] firmware/lib/sp_core/vendor/monocypher/LICENCE.md
```

Then update the version, checksums and tables above, read the upstream
`CHANGELOG.md` for changes to `crypto_ed25519_check`, and run
`pio test -e native -f test_core_ota_manifest` and
`pytest tests/test_firmware_vendor.py` (from `server/`).

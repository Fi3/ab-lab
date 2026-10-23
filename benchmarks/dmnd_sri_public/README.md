
## Public transport interface check

The protected mining tests use a fixed transport interface. This interface is
part of the benchmark requirements. It is separate from the mining scenarios
and assertions. The source in `examples/sri_transport_contract.rs` is public.
Authors and reviewers may read and compile this example. Keep it unchanged.
The restrictions on `tests/**` still apply.

Run these commands from the repository root before you finish implementation
or review. Authors must correct compilation errors and repeat the checks.
Reviewers must report compilation errors as findings:

```sh
cargo check --locked --lib --bin dmnd-client
cargo check --locked --features mining-e2e --example sri_transport_contract
```

These commands do not need Docker. They compile production code and the public
example. They do not compile or run the protected mining tests. The build needs
Rust, a C/C++ toolchain, pkg-config, OpenSSL development files, and Cap'n Proto
(`capnp`). The benchmark executor supplies these tools.

The unchanged `build.rs` selects the transport interface from the root
`Cargo.toml`. A direct dependency named `codec_sv2` selects the legacy interface.
Without that dependency, the following interface is required:

- `demand_sv2_connection` exports `HandshakeRole`, `Initiator`, `Responder`,
  `StandardEitherFrame`, and `StandardSv2Frame` from its crate root.
- `Initiator::without_pk()` and `Responder::from_authority_kp()` construct the
  handshake roles. `HandshakeRole` has `Initiator` and `Responder` variants.
- `noise_connection_tokio::Connection::new::<PoolExtMessages<'static>>()`
  accepts a Tokio TCP stream and a handshake role. Its asynchronous result
  contains a Tokio message receiver, message sender, and two Tokio task abort
  handles. Errors support `Debug` formatting.
- Messages convert to standard SV2 frames. Standard frames convert to transport
  frames, and transport frames convert back to standard frames. Standard frames
  expose their header and mutable payload. The accounting and template
  distribution parsers accept these protocol bytes and can return owned messages.

The example specifies the required types and operations for both interfaces.
The migrated interface is a compatibility requirement of this benchmark. It
does not describe exports that the original upstream connection crate already
provided. Public re-exports are sufficient when the required types already
exist in another module. Internal module layout is otherwise unrestricted.

A successful public check proves interface compatibility only. The independent
host grader builds and runs the unchanged mining suite after the coding and
review sessions close. Docker and the protected suite are not available for
agent validation. Do not inspect the protected test source or run its Docker
command. The host grader also checks the default CLI build, dependency sources,
protocol bytes, allocations, and all mining results.

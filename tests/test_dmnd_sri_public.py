"""The public example must check transport types without compiling test targets."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


CONTRACT = Path(__file__).resolve().parents[1] / "benchmarks/dmnd_sri_public/sri_transport_contract.rs"
EXPORTS = {
    "tokio": "pub use stub_core::{net, sync, task};",
    "demand-share-accounting-ext": "pub mod parser { pub use stub_core::PoolExtMessages; }",
    "roles_logic_sv2": "pub mod parsers { pub use stub_core::{TemplateDistribution, TemplateDistributionTypes}; }",
    "demand-sv2-connection": "pub use stub_core::{HandshakeRole, Initiator, Responder, StandardEitherFrame, StandardSv2Frame};\n"
                             "pub mod noise_connection_tokio { pub use stub_core::Connection; }",
    "codec_sv2": "pub use stub_core::{HandshakeRole, NoiseEncoder, StandardEitherFrame, StandardNoiseDecoder, StandardSv2Frame, State, Error};",
    "noise_sv2": "pub use stub_core::{Initiator, Responder};",
}
STUB = r'''
use std::marker::PhantomData;
#[derive(Debug)]
pub enum Error { MissingBytes(usize), Other }
pub mod net { pub struct TcpStream; }
pub mod task {
    pub struct AbortHandle;
    impl AbortHandle { pub fn abort(&self) {} }
}
pub mod sync {
    pub mod mpsc {
        use std::marker::PhantomData;
        pub struct Receiver<T>(pub PhantomData<T>);
        pub struct Sender<T>(pub PhantomData<T>);
        impl<T> Receiver<T> { pub async fn recv(&mut self) -> Option<T> { None } }
        impl<T> Sender<T> { pub async fn send(&self, _: T) -> Result<(), ()> { Ok(()) } }
    }
}
pub struct Initiator;
pub struct Responder;
pub struct Noise;
pub enum HandshakeRole { Initiator(Box<Initiator>), Responder(Box<Responder>) }
impl Initiator {
    pub fn without_pk() -> Result<Box<Self>, Error> { Ok(Box::new(Self)) }
    pub fn step_0(&mut self) -> Result<[u8; 64], Error> { Ok([0; 64]) }
    pub fn step_2(&mut self, _: [u8; 234]) -> Result<Noise, Error> { Ok(Noise) }
}
impl Responder {
    pub fn from_authority_kp(_: &[u8; 32], _: &[u8; 32], _: std::time::Duration) -> Result<Box<Self>, Error> {
        Ok(Box::new(Self))
    }
    pub fn step_1(&mut self, _: [u8; 64]) -> Result<([u8; 234], Noise), Error> { Ok(([0; 234], Noise)) }
}
pub struct Header;
impl Header {
    pub fn ext_type(&self) -> u16 { 0 }
    pub fn msg_type(&self) -> u8 { 0 }
}
pub struct StandardSv2Frame<T> { bytes: Vec<u8>, message: PhantomData<T> }
pub type StandardEitherFrame<T> = StandardSv2Frame<T>;
impl<T> StandardSv2Frame<T> {
    pub fn get_header(&self) -> Option<Header> { Some(Header) }
    pub fn payload(&mut self) -> &mut [u8] { &mut self.bytes }
    pub fn encoded_length(&self) -> usize { self.bytes.len() }
    pub fn serialize(self, _: &mut [u8]) -> Result<(), Error> { Ok(()) }
    pub fn from_bytes_unchecked(bytes: Vec<u8>) -> Self { Self { bytes, message: PhantomData } }
}
pub struct TemplateDistribution<'a>(PhantomData<&'a mut [u8]>);
pub enum PoolExtMessages<'a> { TemplateDistribution(TemplateDistribution<'a>) }
pub struct TemplateDistributionTypes;
impl TryFrom<u8> for TemplateDistributionTypes {
    type Error = Error;
    fn try_from(_: u8) -> Result<Self, Error> { Ok(Self) }
}
impl<'a> TryFrom<(u8, &'a mut [u8])> for TemplateDistribution<'a> {
    type Error = Error;
    fn try_from(_: (u8, &'a mut [u8])) -> Result<Self, Error> { Ok(Self(PhantomData)) }
}
impl<'a> TryFrom<(u16, u8, &'a mut [u8])> for PoolExtMessages<'a> {
    type Error = Error;
    fn try_from(_: (u16, u8, &'a mut [u8])) -> Result<Self, Error> {
        Ok(Self::TemplateDistribution(TemplateDistribution(PhantomData)))
    }
}
impl PoolExtMessages<'_> {
    pub fn into_static(self) -> PoolExtMessages<'static> {
        PoolExtMessages::TemplateDistribution(TemplateDistribution(PhantomData))
    }
}
impl<'a> TryFrom<PoolExtMessages<'a>> for StandardSv2Frame<PoolExtMessages<'a>> {
    type Error = Error;
    fn try_from(_: PoolExtMessages<'a>) -> Result<Self, Error> { Ok(Self::from_bytes_unchecked(vec![])) }
}
pub struct Connection;
impl Connection {
    pub async fn new<T>(_: net::TcpStream, _: HandshakeRole) -> Result<(
        sync::mpsc::Receiver<StandardEitherFrame<T>>, sync::mpsc::Sender<StandardEitherFrame<T>>,
        task::AbortHandle, task::AbortHandle
    ), Error> {
        Ok((sync::mpsc::Receiver(PhantomData), sync::mpsc::Sender(PhantomData), task::AbortHandle, task::AbortHandle))
    }
}
pub struct State;
impl State { pub fn with_transport_mode(_: Noise) -> Self { Self } }
pub struct StandardNoiseDecoder<T>(PhantomData<T>);
impl<T> StandardNoiseDecoder<T> {
    pub fn new() -> Self { Self(PhantomData) }
    pub fn writable(&mut self) -> &mut [u8] { &mut [] }
    pub fn next_frame(&mut self, _: &mut State) -> Result<StandardEitherFrame<T>, Error> {
        Err(Error::MissingBytes(1))
    }
}
pub struct NoiseEncoder<T>(PhantomData<T>);
impl<T> NoiseEncoder<T> {
    pub fn new() -> Self { Self(PhantomData) }
    pub fn encode(&mut self, _: StandardEitherFrame<T>, _: &mut State) -> Result<Vec<u8>, Error> { Ok(vec![]) }
}
'''


@unittest.skipUnless(shutil.which("cargo"), "Cargo is required for the public compile contract")
class PublicTransportContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write("Cargo.toml", '[package]\nname="contract-fixture"\nversion="0.1.0"\nedition="2021"\n'
                   '[features]\nmining-e2e=[]\n[dependencies]\n' + "".join(
                       f'{name}={{path="vendor/{name}"}}\n' for name in EXPORTS if name != "codec_sv2"))
        self.write("src/lib.rs", "pub fn production() {}\n")
        self.write("tests/protected.rs", 'compile_error!("protected test was compiled");\n')
        self.write("examples/sri_transport_contract.rs", CONTRACT.read_text())
        self.write("build.rs", 'fn main() {\n'
                   ' println!("cargo:rustc-check-cfg=cfg(legacy_sv2_transport)");\n'
                   ' println!("cargo:rerun-if-changed=Cargo.toml");\n'
                   ' if std::fs::read_to_string("Cargo.toml").unwrap().contains("codec_sv2=") {\n'
                   '  println!("cargo:rustc-cfg=legacy_sv2_transport");\n }\n}\n')
        self.package("stub-core", STUB)
        for name, exports in EXPORTS.items():
            self.package(name, exports, dependency=True)
        self.assertEqual(self.cargo("generate-lockfile", "--offline").returncode, 0)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def package(self, name, source, dependency=False):
        manifest = f'[package]\nname="{name}"\nversion="0.1.0"\nedition="2021"\n'
        if dependency:
            manifest += '[dependencies]\nstub-core={path="../stub-core"}\n'
        self.write(f"vendor/{name}/Cargo.toml", manifest)
        self.write(f"vendor/{name}/src/lib.rs", source)

    def cargo(self, *args):
        return subprocess.run(["cargo", *args], cwd=self.root, text=True, capture_output=True,
                              timeout=60, env={**os.environ, "CARGO_TERM_COLOR": "never"})

    def check(self, *args):
        return self.cargo("check", "--offline", "--locked", "--example", "sri_transport_contract", *args)

    def source_bytes(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()
                and "target" not in path.relative_to(self.root).parts}

    def test_public_example_checks_both_feature_sets_without_changing_source(self):
        before = self.source_bytes()
        for args in ((), ("--features", "mining-e2e")):
            with self.subTest(args=args):
                result = self.check(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.source_bytes(), before)

    def test_legacy_selection_uses_codec_without_new_connection_exports(self):
        manifest = self.root / "Cargo.toml"
        manifest.write_text(manifest.read_text() + 'codec_sv2={path="vendor/codec_sv2"}\n')
        self.write("vendor/demand-sv2-connection/src/lib.rs", "")
        self.assertEqual(self.cargo("generate-lockfile", "--offline").returncode, 0)
        result = self.check("--features", "mining-e2e")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_connection_root_exports_fail(self):
        self.write("vendor/demand-sv2-connection/src/lib.rs",
                   "pub mod noise_connection_tokio { pub use stub_core::Connection; }")
        result = self.check("--features", "mining-e2e")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unresolved imports", result.stderr)
        self.assertIn("examples/sri_transport_contract.rs", result.stderr)

    def test_wrong_connection_return_types_fail(self):
        self.write("vendor/stub-core/src/lib.rs", STUB.replace(
            "task::AbortHandle, task::AbortHandle", "task::AbortHandle, ()"))
        result = self.check("--features", "mining-e2e")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mismatched types", result.stderr)
        self.assertIn("examples/sri_transport_contract.rs", result.stderr)

    def test_wrong_handshake_constructor_fails(self):
        self.write("vendor/stub-core/src/lib.rs", STUB.replace(
            "pub fn from_authority_kp(_: &[u8; 32]", "pub fn from_authority_kp(_: &[u8; 31]"))
        result = self.check("--features", "mining-e2e")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mismatched types", result.stderr)
        self.assertIn("examples/sri_transport_contract.rs", result.stderr)

    def test_non_send_connection_future_fails(self):
        self.write("vendor/stub-core/src/lib.rs", STUB.replace(
            "        Ok((sync::mpsc::Receiver", "        let held = std::rc::Rc::new(());\n"
            "        std::future::pending::<()>().await;\n        drop(held);\n"
            "        Ok((sync::mpsc::Receiver"))
        result = self.check("--features", "mining-e2e")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot be sent between threads safely", result.stderr)
        self.assertIn("examples/sri_transport_contract.rs", result.stderr)

    def test_missing_frame_operation_fails(self):
        self.write("vendor/stub-core/src/lib.rs", STUB.replace("fn payload(", "fn hidden_payload("))
        result = self.check("--features", "mining-e2e")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no method named `payload`", result.stderr)
        self.assertIn("examples/sri_transport_contract.rs", result.stderr)


if __name__ == "__main__":
    unittest.main()

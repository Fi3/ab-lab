//! Public compile contract for the connection and frame API.
//! This example does not connect to a pool or execute mining scenarios.
#![allow(dead_code, unused_crate_dependencies)]

#[cfg(legacy_sv2_transport)]
use codec_sv2::{
    HandshakeRole, NoiseEncoder, StandardEitherFrame, StandardNoiseDecoder, StandardSv2Frame, State,
};
use demand_share_accounting_ext::parser::PoolExtMessages;
#[cfg(not(legacy_sv2_transport))]
use demand_sv2_connection::{
    noise_connection_tokio::Connection, HandshakeRole, Initiator, Responder, StandardEitherFrame,
    StandardSv2Frame,
};
#[cfg(legacy_sv2_transport)]
use noise_sv2::{Initiator, Responder};
#[cfg(not(legacy_sv2_transport))]
use tokio::net::TcpStream;
use tokio::{sync::mpsc, task::AbortHandle};

type Message = PoolExtMessages<'static>;
type Frame = StandardEitherFrame<Message>;
type ConnectionParts = (
    mpsc::Receiver<Frame>,
    mpsc::Sender<Frame>,
    AbortHandle,
    AbortHandle,
);

fn diagnostic(error: impl std::fmt::Debug) -> String {
    format!("{error:?}")
}

fn require_send<T: Send + 'static>(_: T) {}

fn handshake_roles(
    public: &[u8; 32],
    secret: &[u8; 32],
) -> Result<(HandshakeRole, HandshakeRole), String> {
    let responder =
        Responder::from_authority_kp(public, secret, std::time::Duration::from_secs(3600))
            .map_err(diagnostic)?;
    let initiator = Initiator::without_pk().map_err(diagnostic)?;
    Ok((
        HandshakeRole::Initiator(initiator),
        HandshakeRole::Responder(responder),
    ))
}

#[cfg(not(legacy_sv2_transport))]
async fn connection(stream: TcpStream, role: HandshakeRole) -> Result<ConnectionParts, String> {
    Connection::new::<Message>(stream, role)
        .await
        .map_err(diagnostic)
}

#[cfg(not(legacy_sv2_transport))]
fn connection_task(stream: TcpStream, role: HandshakeRole, message: Message) {
    require_send(async move {
        let parts = connection(stream, role).await?;
        transport_task(parts, message);
        Ok::<(), String>(())
    });
}

fn transport_task(mut parts: ConnectionParts, message: Message) {
    require_send(async move {
        send(&parts.1, message).await?;
        receive(&mut parts.0).await?;
        abort(parts);
        Ok::<(), String>(())
    });
}

async fn receive(receiver: &mut mpsc::Receiver<Frame>) -> Result<Option<Message>, String> {
    let Some(frame) = receiver.recv().await else {
        return Ok(None);
    };
    let mut frame: StandardSv2Frame<Message> = frame.try_into().map_err(diagnostic)?;
    let header = frame.get_header().ok_or("missing frame header")?;
    let (extension, kind) = (header.ext_type(), header.msg_type());
    if extension & 0x7fff == 0
        && roles_logic_sv2::parsers::TemplateDistributionTypes::try_from(kind).is_ok()
    {
        return roles_logic_sv2::parsers::TemplateDistribution::try_from((kind, frame.payload()))
            .map(|message| Some(PoolExtMessages::TemplateDistribution(message).into_static()))
            .map_err(diagnostic);
    }
    PoolExtMessages::try_from((extension, kind, frame.payload()))
        .map(|message| Some(message.into_static()))
        .map_err(diagnostic)
}

async fn send(sender: &mpsc::Sender<Frame>, message: Message) -> Result<(), String> {
    let frame: StandardSv2Frame<Message> = message.try_into().map_err(diagnostic)?;
    sender
        .send(frame.into())
        .await
        .map_err(|_| "connection closed".to_owned())
}

fn abort(parts: ConnectionParts) {
    parts.2.abort();
    parts.3.abort();
}

#[cfg(legacy_sv2_transport)]
fn handshake_bytes<const N: usize>() -> [u8; N] {
    [0; N]
}

#[cfg(legacy_sv2_transport)]
fn legacy_transport(role: HandshakeRole, outgoing: Frame) -> Result<(), String> {
    fn require_send_type<T: Send + 'static>() {}
    require_send_type::<HandshakeRole>();
    require_send_type::<State>();
    require_send_type::<StandardNoiseDecoder<Message>>();
    require_send_type::<NoiseEncoder<Message>>();
    let noise = match role {
        HandshakeRole::Initiator(mut initiator) => {
            let first = initiator.step_0().map_err(diagnostic)?;
            let _: &[u8] = &first;
            initiator.step_2(handshake_bytes()).map_err(diagnostic)?
        }
        HandshakeRole::Responder(mut responder) => {
            let (response, noise) = responder.step_1(handshake_bytes()).map_err(diagnostic)?;
            let _: &[u8] = &response;
            noise
        }
    };
    let mut state = State::with_transport_mode(noise);
    let mut decoder = StandardNoiseDecoder::<Message>::new();
    let _: &mut [u8] = decoder.writable();
    match decoder.next_frame(&mut state) {
        Ok(frame) => {
            let frame: StandardSv2Frame<Message> = frame.try_into().map_err(diagnostic)?;
            let mut bytes = vec![0; frame.encoded_length()];
            frame.serialize(&mut bytes).map_err(diagnostic)?;
            let frame = StandardSv2Frame::<Message>::from_bytes_unchecked(bytes.into());
            let _: Frame = frame.into();
        }
        Err(codec_sv2::Error::MissingBytes(_)) => {}
        Err(error) => return Err(diagnostic(error)),
    }
    let mut encoder = NoiseEncoder::<Message>::new();
    let bytes = encoder.encode(outgoing, &mut state).map_err(diagnostic)?;
    let _: &[u8] = bytes.as_ref();
    Ok(())
}

fn main() {}

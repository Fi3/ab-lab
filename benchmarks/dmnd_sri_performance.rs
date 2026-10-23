use binary_sv2::{GetSize, Seq0255, Sv2Option};
use framing_sv2::framing::Sv2Frame;
use roles_logic_sv2::mining_sv2::{NewExtendedMiningJob, SubmitSharesExtended};
#[cfg(not(legacy_sv2_transport))]
use roles_logic_sv2::{binary_sv2, framing_sv2};
use sha2::{Digest, Sha256};
use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
    hint::black_box,
};

const SIZE_ITERATIONS: usize = 10_000;
const WIRE_ITERATIONS: usize = 256;

struct CountingAllocator;
#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;
thread_local! { static ALLOCATIONS: Cell<Option<usize>> = const { Cell::new(None) }; }

fn record_allocation() {
    let _ = ALLOCATIONS.try_with(|count| {
        if let Some(value) = count.get() {
            count.set(Some(value + 1));
        }
    });
}

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        unsafe { System.alloc(layout) }
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        record_allocation();
        unsafe { System.alloc_zeroed(layout) }
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        record_allocation();
        unsafe { System.realloc(pointer, layout, size) }
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        unsafe { System.dealloc(pointer, layout) }
    }
}

fn count_allocations(operation: impl FnOnce()) -> usize {
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            ALLOCATIONS.with(|count| count.set(None));
        }
    }
    ALLOCATIONS.with(|count| count.set(Some(0)));
    let _reset = Reset;
    operation();
    ALLOCATIONS.with(|count| count.get().unwrap())
}

fn mining_job() -> NewExtendedMiningJob<'static> {
    NewExtendedMiningJob {
        channel_id: 1,
        job_id: 1,
        min_ntime: Sv2Option::new(Some(1)),
        version: 0x20000000,
        version_rolling_allowed: true,
        merkle_path: Seq0255::new(vec![[1; 32].into(); 12]).unwrap(),
        coinbase_tx_prefix: vec![1; 100].try_into().unwrap(),
        coinbase_tx_suffix: vec![2; 500].try_into().unwrap(),
    }
}

fn extended_share() -> SubmitSharesExtended<'static> {
    SubmitSharesExtended {
        channel_id: 7,
        sequence_number: 8,
        job_id: 9,
        nonce: 10,
        ntime: 11,
        version: 0x20000000,
        extranonce: vec![12; 28].try_into().unwrap(),
    }
}

fn expected_job() -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend([1u32.to_le_bytes(), 1u32.to_le_bytes()].concat());
    bytes.push(1);
    bytes.extend(1u32.to_le_bytes());
    bytes.extend(0x20000000u32.to_le_bytes());
    bytes.extend([1, 12]);
    bytes.extend([1; 12 * 32]);
    bytes.extend(100u16.to_le_bytes());
    bytes.extend([1; 100]);
    bytes.extend(500u16.to_le_bytes());
    bytes.extend([2; 500]);
    bytes
}

fn expected_share() -> Vec<u8> {
    let mut bytes = Vec::new();
    for value in [7u32, 8, 9, 10, 11, 0x20000000] {
        bytes.extend(value.to_le_bytes());
    }
    bytes.push(28);
    bytes.extend([12; 28]);
    bytes
}

fn expected_frame(payload: &[u8], message_type: u8) -> Vec<u8> {
    let mut bytes = vec![0, 128, message_type];
    bytes.extend(&(payload.len() as u32).to_le_bytes()[..3]);
    bytes.extend(payload);
    bytes
}

#[test]
fn lab_sri_performance() {
    assert_eq!(count_allocations(|| drop(black_box(Box::new(1u64)))), 1);
    let job = mining_job();
    let share = extended_share();
    let job_frame: Sv2Frame<_, Vec<u8>> =
        Sv2Frame::from_message(job.clone(), 0x1f, 0, true).unwrap();
    let share_frame: Sv2Frame<_, Vec<u8>> =
        Sv2Frame::from_message(share.clone(), 0x1b, 0, true).unwrap();
    let mut size_checksum = 0;
    let size_allocations = count_allocations(|| {
        for _ in 0..SIZE_ITERATIONS {
            size_checksum += black_box(&job).get_size()
                + black_box(&share).get_size()
                + black_box(&job_frame).encoded_length()
                + black_box(&share_frame).encoded_length();
        }
    });
    assert_eq!(
        size_allocations, 0,
        "message and frame size queries must not allocate"
    );
    assert_eq!(size_checksum, SIZE_ITERATIONS * (1007 + 53 + 1013 + 59));

    let job_wire = expected_job();
    let share_wire = expected_share();
    let job_frame_wire = expected_frame(&job_wire, 0x1f);
    let share_frame_wire = expected_frame(&share_wire, 0x1b);
    let mut job_buffer = vec![0; job_frame_wire.len()];
    let mut share_buffer = vec![0; share_frame_wire.len()];
    let mut digest = Sha256::new();
    for _ in 0..WIRE_ITERATIONS {
        assert_eq!(
            binary_sv2::to_bytes(black_box(job.clone())).unwrap(),
            job_wire
        );
        assert_eq!(
            binary_sv2::to_bytes(black_box(share.clone())).unwrap(),
            share_wire
        );
        black_box(job_frame.clone())
            .serialize(&mut job_buffer)
            .unwrap();
        black_box(share_frame.clone())
            .serialize(&mut share_buffer)
            .unwrap();
        assert_eq!(job_buffer, job_frame_wire);
        assert_eq!(share_buffer, share_frame_wire);
        digest.update(&job_buffer);
        digest.update(&share_buffer);
    }
    let evidence = serde_json::json!({
        "schema": "dmnd-sri-performance/v1", "size_iterations": SIZE_ITERATIONS,
        "wire_iterations": WIRE_ITERATIONS, "size_allocations": size_allocations,
        "size_checksum": size_checksum, "job_bytes": job.get_size(), "share_bytes": share.get_size(),
        "job_frame_bytes": job_frame.encoded_length(), "share_frame_bytes": share_frame.encoded_length(),
        "wire_sha256": format!("{:x}", digest.finalize()),
    });
    println!("LAB_SRI_PERFORMANCE {}", evidence);
}

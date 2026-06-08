// Copyright 2026 The MathWorks, Inc.

import { renderHook, act } from '@testing-library/react-hooks';
import { useTimeoutFn } from './useTimeoutFn';

describe('useTimeoutFn', () => {
    beforeEach(() => {
        // Use fake timers so we can control time advancement in tests
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('should call callback after the specified delay', () => {
        const callback = vi.fn();
        renderHook(() => useTimeoutFn(callback, 1000));

        // Callback should not fire immediately
        expect(callback).not.toHaveBeenCalled();

        // After the delay elapses, callback fires exactly once (not repeating like setInterval)
        vi.advanceTimersByTime(1000);
        expect(callback).toHaveBeenCalledTimes(1);
    });

    it('should return isReady, clear, and set functions', () => {
        // The hook returns a tuple of [isReady, clear, set] for controlling the timeout
        const callback = vi.fn();
        const { result } = renderHook(() => useTimeoutFn(callback, 1000));

        const [isReady, clear, set] = result.current;
        expect(typeof isReady).toBe('function');
        expect(typeof clear).toBe('function');
        expect(typeof set).toBe('function');
    });

    it('should report ready state correctly', () => {
        // isReady() returns false while waiting, true after the timeout fires
        const callback = vi.fn();
        const { result } = renderHook(() => useTimeoutFn(callback, 1000));
        const [isReady] = result.current;

        // Still waiting — not ready yet
        expect(isReady()).toBe(false);

        // Timeout has fired — now ready
        vi.advanceTimersByTime(1000);
        expect(isReady()).toBe(true);
    });

    it('should cancel timeout when clear is called', () => {
        const callback = vi.fn();
        const { result } = renderHook(() => useTimeoutFn(callback, 1000));
        const [isReady, clear] = result.current;

        // Call clear() to cancel the pending timeout
        act(() => {
            clear();
        });

        // Even after waiting well past the delay, callback should never fire
        vi.advanceTimersByTime(2000);
        expect(callback).not.toHaveBeenCalled();
        // isReady() returns null when cleared (distinct from false=pending, true=fired)
        expect(isReady()).toBe(null);
    });

    it('should restart timeout when set is called', () => {
        const callback = vi.fn();
        const { result } = renderHook(() => useTimeoutFn(callback, 1000));
        const [, , set] = result.current;

        // Advance 500ms into the original 1000ms timeout
        vi.advanceTimersByTime(500);

        // Call set() to restart the timeout from scratch
        act(() => {
            set();
        });

        // 500ms after restart — should NOT have fired (needs full 1000ms from restart)
        vi.advanceTimersByTime(500);
        expect(callback).not.toHaveBeenCalled();

        // 1000ms after restart — now it fires
        vi.advanceTimersByTime(500);
        expect(callback).toHaveBeenCalledTimes(1);
    });

});

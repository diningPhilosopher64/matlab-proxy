// Copyright 2026 The MathWorks, Inc.

import { renderHook } from '@testing-library/react-hooks';
import { useInterval } from './useInterval';

describe('useInterval', () => {
    beforeEach(() => {
        // Use fake timers so we can control time advancement in tests
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('should call callback at the specified interval', () => {
        const callback = vi.fn();
        renderHook(() => useInterval(callback, 1000));

        // Callback should not fire immediately
        expect(callback).not.toHaveBeenCalled();

        // After 1s, callback should fire once
        vi.advanceTimersByTime(1000);
        expect(callback).toHaveBeenCalledTimes(1);

        // After another 1s, callback should fire again (repeating)
        vi.advanceTimersByTime(1000);
        expect(callback).toHaveBeenCalledTimes(2);
    });

    it('should not call callback when delay is null', () => {
        // Passing null as delay should disable the interval entirely
        const callback = vi.fn();
        renderHook(() => useInterval(callback, null));

        vi.advanceTimersByTime(5000);
        expect(callback).not.toHaveBeenCalled();
    });

    it('should clear interval on unmount', () => {
        const callback = vi.fn();
        const { unmount } = renderHook(() => useInterval(callback, 1000));

        // Verify it fires at least once
        vi.advanceTimersByTime(1000);
        expect(callback).toHaveBeenCalledTimes(1);

        // After unmount, interval should be cleared and callback should not fire again
        unmount();

        vi.advanceTimersByTime(5000);
        expect(callback).toHaveBeenCalledTimes(1);
    });

    it('should use the latest callback', () => {
        // The hook stores the callback in a ref, so even though the interval
        // was set up with the first callback, it should call the updated one
        const results = [];
        const { rerender } = renderHook(
            ({ callback }) => useInterval(callback, 1000),
            { initialProps: { callback: () => results.push('first') } }
        );

        vi.advanceTimersByTime(1000);
        expect(results).toEqual(['first']);

        // Swap to a new callback mid-interval
        rerender({ callback: () => results.push('second') });

        // Next tick should use the new callback, not the old one
        vi.advanceTimersByTime(1000);
        expect(results).toEqual(['first', 'second']);
    });

});

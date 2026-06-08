// Copyright 2026 The MathWorks, Inc.

import { useCallback, useEffect, useRef } from 'react';

export function useTimeoutFn (fn, ms) {
    const ready = useRef(false);
    const timeout = useRef(null);
    const callback = useRef(fn);

    const isReady = useCallback(() => ready.current, []);

    const clear = useCallback(() => {
        ready.current = null;
        if (timeout.current) {
            clearTimeout(timeout.current);
        }
    }, []);

    const set = useCallback(() => {
        ready.current = false;
        if (timeout.current) {
            clearTimeout(timeout.current);
        }
        timeout.current = setTimeout(() => {
            ready.current = true;
            callback.current();
        }, ms);
    }, [ms]);

    useEffect(() => {
        callback.current = fn;
    }, [fn]);

    useEffect(() => {
        set();
        return clear;
    }, [ms]);

    return [isReady, clear, set];
}

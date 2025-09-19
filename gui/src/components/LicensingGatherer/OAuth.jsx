// Copyright 2023-2025 The MathWorks, Inc.

import React from 'react';
import { useDispatch } from 'react-redux';
import {
    fetchLoginWithOAuth
} from '../../actionCreators';
import './ExistingLicense.css';

function OAuth () {
    const dispatch = useDispatch();

    function submitForm (event) {
        event.preventDefault();
        dispatch(fetchLoginWithOAuth());
    }

    return (
        <div id="OAuth">
            <form onSubmit={submitForm}>
                <div className='form-group'>
                    <p>
                        Sign in to your MathWorks Account to access MATLAB through this application.
                    </p>
                    <br/>
                    <input type="submit" id="submit" value="Sign In" className="btn btn_color_blue" />
                </div>
            </form>
        </div>
    );
}

export default OAuth;

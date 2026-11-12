import { io } from "socket.io-client"

import { getCachedListResource } from "frappe-ui/src/resources/listResource"
import { getCachedResource } from "frappe-ui/src/resources/resources"

export function initSocket() {
	let host = window.location.hostname
	let siteName = window.site_name
	let socketio_port = window.frappe?.boot?.socketio_port || 9000
	// A production build reaches socket.io through the page's own origin (the web server
	// proxies /socket.io). Only the Vite dev server runs apart, so it uses socketio_port.
	let url = import.meta.env.DEV
		? `http://${host}:${socketio_port}/${siteName}`
		: `${window.location.origin}/${siteName}`
	let socket = io(url, {
		withCredentials: true,
		reconnectionAttempts: 5,
	})

	socket.on("hrms:refetch_resource", (data) => {
		if (data.cache_key) {
			let resource =
				getCachedResource(data.cache_key) ||
				getCachedListResource(data.cache_key)

			if (resource) {
				resource.reload()
			}
		}
	})

	return socket
}

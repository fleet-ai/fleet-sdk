

class BrowserController:
    """Controller for browser operations on a Fleet instance."""


    async def describe(self) -> Dict[str, Any]:
        """Stop the browser instance.
        
        Returns:
            Response data containing confirmation
        """
        return await self._client._request("GET", "/api/v1/env/resource/cdp/describe")
    
    async def start(self) -> Dict[str, Any]:
        """Start the browser instance.
        
        Returns:
            Response data containing browser status
        """
        return await self._client._request("POST", "/api/v1/env/resource/cdp/start")
